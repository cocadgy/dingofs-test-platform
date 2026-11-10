"""Transactional one-child decisions; commit before executing a decision.

An attempted launch is never issued again. Event cursor, accepted events and
resource ledger share a transaction. Remote facts come from our supervisor.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from dingofs_platform.auth.models import User
from dingofs_platform.operations.leases import (LeaseRequest, lock_keys, ensure_leases,
                                               release_verified, completion_evidence)
from .models import FunctionalRun, FunctionalModuleRun, FunctionalEvent, FunctionalResource, ACTIVE
from .preflight import revalidate_binding
from .results import evaluate_child, ChildResultError
from .submission import NormalizedSubmission


def now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DispatchDecision:
    action: str
    child_id: str | None = None
    payload: dict = field(default_factory=dict)
    cursor: dict = field(default_factory=dict)
    cancel: bool = False


def lease_requests(parent):
    """Keep the original union even after inventory aliases change."""
    binding = parent.snapshot.get('runtime_binding', {})
    routes = binding.get('resolved_targets', [])
    mutations = {(t['host'], t['user']) for env in parent.snapshot['environment_snapshots'].values()
                 for t in env['targets'] if t['mutates']}
    keys = {'machine:' + r['machine_id'] for r in routes
            if (r['source_host'], r['user']) in mutations or (r['address'], r['user']) in mutations}
    return [LeaseRequest('cluster:' + parent.cluster_id),
            LeaseRequest('runtime:' + parent.machine_id, 'shared'),
            *[LeaseRequest(key) for key in sorted(keys)]]


def _locked(db, run_id):
    parent = db.get(FunctionalRun, run_id)
    if not parent or parent.version != 2:
        return None, [], []
    requests = lease_requests(parent)
    lock_keys(db, requests)
    parent = db.get(FunctionalRun, run_id, with_for_update=True, populate_existing=True)
    children = list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id)
                    .order_by(FunctionalModuleRun.position).with_for_update().execution_options(populate_existing=True)))
    return parent, children, requests


def _not_run(child, reason):
    child.state = 'not_run'
    child.finished_at = now()
    child.error = reason
    child.result = {'child_state': 'not_run', 'stage': 'waiting', 'not_run': list(child.cases),
                    'case_counts': dict(total=len(child.cases), completed=0, passed=0, failed=0,
                                        skipped=0, known_bugs=0), 'case_results': [], 'attempt_records': [],
                    'failed_cases': [], 'missing': [], 'suite_errors': 0, 'retained_resources': [],
                    'cleanup_status': 'not_started', 'recovery_status': 'not_required',
                    'report_status': 'missing', 'report_path': None, 'end_proof': False, 'may_continue': False}


def _finish(db, parent, children, requests, state, *, releasable=False):
    parent.state, parent.finished_at = state, now()
    parent.phase = '等待资源复核' if state == 'needs_attention' else '已结束'
    parent.progress = 100
    for child in children:
        if child.state == 'queued' and child.launch_attempted_at is None:
            _not_run(child, '前序任务未安全完成或父任务已取消')
    db.flush()
    if releasable:
        release_verified(db, 'functional:' + parent.id, completion_evidence('functional:' + parent.id, requests))


def _payload(parent, child):
    binding = parent.snapshot['runtime_binding']
    return {'version': 2, 'parent_id': parent.id, 'child_id': child.id, 'module': child.module,
            'env_name': child.environment_snapshot['env_name'], 'cases': list(child.cases),
            'hashes': dict(child.case_hashes), 'retries': child.retries,
            'launch_token': child.remote_identity['launch_token'],
            'immutable_path': binding['immutable_path'], 'runtime_manifest': binding['functional_runtime'],
            'context': {'version': 1, 'parent_id': parent.id, 'child_id': child.id,
                        'module': child.module, 'env_name': child.environment_snapshot['env_name'],
                        'retries': child.retries, 'source_manifest': child.environment_snapshot['source_manifest'],
                        'approved_targets': binding['approved_targets'],
                        'resolved_targets': binding['resolved_targets'],
                        'functional_runtime': binding['functional_runtime']}}


def advance_parent(db: Session, run_id: str) -> DispatchDecision:
    parent, children, requests = _locked(db, run_id)
    if not parent or parent.state not in ACTIVE:
        return DispatchDecision('done')
    if parent.cancel_requested and all(c.launch_attempted_at is None for c in children):
        _finish(db, parent, children, requests, 'cancelled', releasable=True)
        return DispatchDecision('done')
    owner = 'functional:' + run_id
    if not ensure_leases(db, owner, requests).acquired:
        parent.phase = '等待目标资源释放'
        return DispatchDecision('wait')
    previous = []
    for child in children:
        if child.state in ('success', 'failed') and child.result.get('may_continue'):
            previous.append(child)
            continue
        if child.state not in ACTIVE:
            _finish(db, parent, children, requests, 'needs_attention')
            return DispatchDecision('done')
        if child.launch_attempted_at is None:
            if parent.cancel_requested:
                _finish(db, parent, children, requests, 'cancelled', releasable=True)
                return DispatchDecision('done')
            try:
                actor = db.get(User, parent.creator_id)
                request = NormalizedSubmission.model_validate({k: v for k, v in parent.snapshot.items()
                                                              if k in NormalizedSubmission.model_fields})
                revalidate_binding(db, actor, request, parent.snapshot.get('runtime_binding'), owner=owner,
                                   admitted_run_id=parent.id)
            except Exception:
                _not_run(child, '启动前复检失败，请重新预检；尚未启动此模块。')
                child.state = 'failed'
                child.result = {**child.result, 'child_state': 'failed'}
                parent.error = child.error
                _finish(db, parent, children, requests, 'failed', releasable=True)
                return DispatchDecision('done')
            child.launch_attempted_at = now()
            child.remote_identity = {'launch_token': uuid4().hex, 'cursor': {}}
            child.state, parent.state, parent.phase = 'running', 'running', '启动 ' + child.module
            db.flush()
            return DispatchDecision('launch', child.id, _payload(parent, child), {})
        if parent.cancel_requested or child.deadline is not None and now() >= child.deadline:
            if not child.cancel_requested:
                child.cancel_requested, child.cancel_requested_at = True, now()
                child.remote_identity = {**child.remote_identity, 'timeout': not parent.cancel_requested}
            child.state, parent.state = 'cancelling', 'cancelling'
        if child.cancel_requested_at and now() >= child.cancel_requested_at + timedelta(seconds=600):
            child.state = 'needs_attention'
            child.error = '取消后 600 秒仍未确认安全结束；保留资源占用。'
            _finish(db, parent, children, requests, 'needs_attention')
            return DispatchDecision('done')
        return DispatchDecision('poll', child.id, _payload(parent, child),
                                deepcopy(child.remote_identity.get('cursor', {})), child.cancel_requested)
    state = 'failed' if any(child.state == 'failed' for child in previous) else 'success'
    _finish(db, parent, children, requests, state, releasable=True)
    return DispatchDecision('done')


def record_observation(db: Session, run_id: str, child_id: str, observation: dict):
    parent, children, requests = _locked(db, run_id)
    if not parent or parent.state not in ACTIVE:
        return
    child = next(c for c in children if c.id == child_id)
    identity = deepcopy(child.remote_identity)
    if child.state not in ACTIVE or observation.get('cursor_before', {}) != identity.get('cursor', {}):
        return
    if observation.get('zero_start') == {'child_id': child.id, 'launch_token': identity['launch_token']} and not identity.get('process'):
        _not_run(child, '启动前已确认取消')
        child.state = 'cancelled'
        child.result = {**child.result, 'child_state': 'cancelled'}
        child.remote_identity = {**identity, 'zero_start': observation['zero_start']}
        _finish(db, parent, children, requests, 'cancelled', releasable=True)
        return
    if observation.get('missing') or observation.get('transport_error'):
        child.state, parent.state = 'unknown', 'unknown'
        child.error = '远端状态未确认；仅查询，不会重复启动。'
        return
    process = observation.get('process')
    if process:
        if (process.get('child_id') != child.id or process.get('launch_token') != identity['launch_token']
                or type(process.get('pid')) is not int or process['pid'] <= 0 or not process.get('start_time')):
            observation = {**observation, 'protocol_error': 'process identity mismatch'}
        elif identity.get('process') and any(process.get(k) != identity['process'].get(k)
                                              for k in ('child_id', 'launch_token', 'pid', 'start_time')):
            observation = {**observation, 'protocol_error': 'process identity changed'}
        else:
            identity['process'] = process
            if child.started_at is None:
                try:
                    started = datetime.fromisoformat(process['started_at'])
                    if started.tzinfo is None:
                        raise ValueError('missing timezone')
                    child.started_at = started
                    child.deadline = started + timedelta(minutes=child.timeout_minutes)
                except (ValueError, KeyError, TypeError):
                    observation = {**observation, 'protocol_error': 'invalid process start timestamp'}
    batch = observation.get('event_batch')
    events = list(db.scalars(select(FunctionalEvent.record).where(FunctionalEvent.child_id == child.id)
                             .order_by(FunctionalEvent.seq)))
    proposed = events + (batch['events'] if batch else [])
    snapshot = {'parent_id': parent.id, 'child_id': child.id, 'module': child.module,
                'cases': child.cases, 'launch_token': identity['launch_token']}
    binding = parent.snapshot['runtime_binding']
    targets = {(target['host'], target['user']) for target in child.environment_snapshot['targets']}
    snapshot['expected_targets'] = [r for r in binding['resolved_targets']
        if (r['source_host'], r['user']) in targets]
    remote = {**observation, 'cancel_requested': child.cancel_requested, 'timeout': identity.get('timeout', False)}
    if observation.get('has_more'):
        remote.pop('end_proof', None)
    if batch and batch.get('partial_tail') and observation.get('end_proof'):
        remote['protocol_error'] = 'incomplete terminal event line'
    if remote.get('end_proof') and not remote.get('journal_verified'):
        remote['protocol_error'] = 'resource journal was not independently reconciled'
    if identity.get('protocol_error'):
        remote['protocol_error'] = identity['protocol_error']
    if remote.get('protocol_error'):
        identity['protocol_error'] = remote['protocol_error']
        if not child.cancel_requested:
            child.cancel_requested, child.cancel_requested_at = True, now()
        remote['cancel_requested'] = True
    try:
        evaluated = evaluate_child(snapshot, proposed, remote)
    except ChildResultError:
        # Keep the last valid cursor, cancel at a safe boundary, and keep
        # polling for positive end proof. Bad events are never committed.
        identity['protocol_error'] = 'event stream differs from frozen plan'
        remote['protocol_error'] = identity['protocol_error']
        remote['cancel_requested'] = True
        if not child.cancel_requested:
            child.cancel_requested, child.cancel_requested_at = True, now()
        batch, proposed = None, events
        evaluated = evaluate_child(snapshot, events, remote)
    # The pure evaluator cannot know whether dispatch was already attempted.
    # A persisted attempt without a process identity is uncertain, not queued.
    if evaluated.child_state == 'queued' and child.launch_attempted_at is not None:
        evaluated = replace(evaluated, child_state='unknown')
    if batch:
        for event in batch['events']:
            db.add(FunctionalEvent(child_id=child.id, seq=event['seq'], record=event))
        identity['cursor'] = ({'offset': batch['new_offset'], 'file_identity': batch['file_identity'],
                               'last_event': batch['last_event']} if batch['new_offset'] else {})
    resources = {}
    for event in proposed:
        if event['type'] == 'resource_changed':
            resource = event['data']['resource']
            resources[resource['id']] = resource
    for resource in evaluated.retained_resources:
        resources[resource['id']] = resource
    for resource_id, resource in resources.items():
        row = db.scalar(select(FunctionalResource).where(FunctionalResource.child_id == child.id,
                                                        FunctionalResource.resource_id == resource_id))
        if row is None:
            row = FunctionalResource(child_id=child.id, resource_id=resource_id)
            db.add(row)
        for key in ('kind', 'cluster', 'host', 'user', 'name', 'path', 'port', 'owned', 'phase', 'remote_identity'):
            setattr(row, key, deepcopy(resource[key]))
    identity['remote_state'] = {k: v for k, v in remote.items()
                                if k not in ('event_batch', 'cursor_before', 'log')}
    for key in ('root', 'output'):
        if key in observation:
            identity[key] = observation[key]
    child.remote_identity = identity
    child.result = asdict(evaluated)
    child.state = evaluated.child_state
    child.error = '远端事件或进程证据不完整' if remote.get('protocol_error') else ''
    parent.log = observation.get('log', parent.log)[-131072:]
    parent.phase = child.module + ': ' + evaluated.stage
    completed = sum(c.result.get('case_counts', {}).get('completed', 0) for c in children)
    parent.progress = int(100 * completed / max(1, sum(len(c.cases) for c in children)))
    if child.state in ('success', 'failed', 'cancelled', 'needs_attention'):
        child.finished_at = now() if evaluated.end_proof else None
        if not evaluated.may_continue:
            safe_cancel = (evaluated.end_proof and evaluated.cleanup_status == 'cleaned'
                           and evaluated.recovery_status in ('recovered', 'not_required')
                           and not evaluated.retained_resources and not remote.get('protocol_error')
                           and child.state == 'cancelled')
            _finish(db, parent, children, requests, 'cancelled' if safe_cancel else 'needs_attention',
                    releasable=safe_cancel)
    elif child.cancel_requested:
        child.state, parent.state = 'cancelling', 'cancelling'
    else:
        parent.state = 'unknown' if child.state == 'unknown' else 'running'
