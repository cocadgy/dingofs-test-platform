"""Durable orchestration with real database transactions and isolated transports."""
import copy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import importlib.util
import json

import pytest
from sqlalchemy import event, select

from test_functional_submission_v2 import source, ready, normalize
from dingofs_platform.auth.models import User
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalEvent
from dingofs_platform.functional.submission import create_run
from dingofs_platform.operations.models import OperationLease


@pytest.fixture(autouse=True)
def deny_ssh(monkeypatch):
    import paramiko
    from dingofs_platform.functional import transport, preflight
    def denied(*args, **kwargs):
        raise AssertionError('unmocked remote I/O forbidden')
    monkeypatch.setattr(paramiko.SSHClient, 'connect', denied)
    monkeypatch.setattr(transport.Transport, 'call', denied)
    monkeypatch.setattr(preflight, 'execute', denied)


def scheduler():
    assert importlib.util.find_spec('dingofs_platform.functional.scheduler'), 'durable scheduler missing'
    from dingofs_platform.functional import scheduler
    return scheduler


@pytest.fixture
def job(app, ready, monkeypatch):
    module = scheduler()
    request = normalize(ready)
    with app.state.session_factory.begin() as db:
        from dingofs_platform.inventory.models import Cluster, Machine
        actor = db.scalar(select(User).where(User.username == 'admin'))
        machine = db.get(Machine, db.get(Cluster, request.cluster_id).management_machine_id)
        binding = {'immutable_path': '/opt/dtt/pinned/dtt', 'functional_runtime': {'version': 2},
                   'approved_targets': [], 'resolved_targets': [],
                   'control_connection': [machine.address, machine.ssh_port, machine.ssh_user]}
        row = create_run(db, actor, request, runtime_binding=binding)
        run_id = row.id
    monkeypatch.setattr(module, 'revalidate_binding', lambda *args, **kwargs: binding)
    app.state.settings.functional_guided_enabled = True
    return run_id


def advance(app, job):
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        return scheduler().advance_parent(db, job)


@pytest.fixture
def trusted_origin():
    def attach_origin(mapper, connection, row):
        row.snapshot = {**row.snapshot, 'rerun_of': 'trusted-server-origin'}
    event.listen(FunctionalRun, 'before_insert', attach_origin)
    try:
        yield
    finally:
        event.remove(FunctionalRun, 'before_insert', attach_origin)


@pytest.fixture
def origin_job(trusted_origin, job):
    return job


def test_trusted_origin_metadata_does_not_prevent_dispatch(app, origin_job):
    with app.state.session_factory() as db:
        row = db.get(FunctionalRun, origin_job)
        digest = row.request_digest
        assert row.snapshot['rerun_of'] == 'trusted-server-origin'
    assert advance(app, origin_job).action == 'launch'
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, origin_job).request_digest == digest


def children(app, job):
    with app.state.session_factory() as db:
        return list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == job)
                               .order_by(FunctionalModuleRun.position)))


def held(app, job):
    with app.state.session_factory() as db:
        return list(db.scalars(select(OperationLease).where(OperationLease.owner == 'functional:' + job,
                               OperationLease.released_at.is_(None))))


def finished(decision, *, cleanup='cleaned', recovery='not_required', retry=False, failed=False):
    payload = decision.payload
    case = payload['cases'][0]
    rows = []
    def emit(kind, data, path=None, attempt=None):
        rows.append(dict(version=2, seq=len(rows)+1, time='2026-11-10T00:00:00Z', type=kind,
            stage='execution', parent_id=payload['parent_id'], child_id=payload['child_id'],
            module=payload['module'], case_path=path, attempt=attempt, data=data))
    results = []
    if retry:
        emit('attempt_finished', {'status': 'FAIL'}, case, 1)
        results.append(dict(case_path=case, attempt=1, status='FAIL', final=False))
    attempt = 2 if retry else 1
    status = 'FAIL' if failed else 'PASS'
    emit('attempt_finished', {'status': status}, case, attempt)
    emit('case_finished', {'status': status, 'final': True}, case, attempt)
    results.append(dict(case_path=case, attempt=attempt, status=status, final=True))
    emit('suite_finished', dict(status='failed' if failed else 'completed', cancelled=False,
        total=1, completed=1, unexecuted=0, passed=int(not failed), failed=int(failed), skipped=0,
        known_bugs=0, suite_errors=0, cleanup_status=cleanup, recovery_status=recovery,
        retained_resources=[], results=results, execution_targets=[], report_paths={}))
    process = dict(state='exited', child_id=payload['child_id'], launch_token=payload['launch_token'],
                   pid=123, start_time='8675309', started_at='2026-11-10T00:00:00+00:00')
    proof = {key: process[key] for key in ('child_id', 'launch_token', 'pid', 'start_time')}
    proof['returncode'] = int(failed)
    return dict(process=process, returncode=int(failed), end_proof=proof, events=rows, journal_verified=True)


def ingest(app, job, decision, remote, tmp_path):
    from dingofs_platform.functional.event_reader import read_events
    data = copy.deepcopy(remote)
    events = data.pop('events', [])
    path = tmp_path / decision.child_id
    path.write_text(''.join(json.dumps(row) + '\n' for row in events))
    data['event_batch'] = asdict(read_events(path, 0))
    data['has_more'] = False
    data['cursor_before'] = decision.cursor
    with app.state.session_factory.begin() as db:
        scheduler().record_observation(db, job, decision.child_id, data)


def test_response_lost_does_not_relaunch_child(app, job):
    launches = []
    class Fake:
        def __init__(self, config): pass
        def start_child(self, payload):
            launches.append(payload)
            raise OSError('response lost after launch')
        def poll_child(self, payload, cursor, cancel=False):
            return {'missing': True, 'cursor_before': cursor}
    app.state.functional_transport = Fake
    for _ in range(3):
        app.state.functional_manager.process(job)
    assert len(launches) == 1
    first, second = children(app, job)
    assert first.state == 'unknown' and second.launch_attempted_at is None
    assert first.remote_identity['launch_token'] == launches[0]['launch_token']
    assert held(app, job)


@pytest.mark.parametrize('cleanup,recovery', [('retained', 'not_required'), ('failed', 'not_required'),
                                            ('cleaned', 'failed')])
def test_retained_failure_marks_remaining_not_run(app, job, tmp_path, cleanup, recovery):
    decision = advance(app, job)
    ingest(app, job, decision, finished(decision, cleanup=cleanup, recovery=recovery), tmp_path)
    assert advance(app, job).action == 'done'
    first, second = children(app, job)
    assert first.state != 'success'
    assert first.result['case_counts']['passed'] == 1
    assert second.state == 'not_run' and second.result['not_run'] == ['b.yaml']
    assert held(app, job)


def test_timeout_starts_at_child_start_and_grace_is_600_seconds(app, job, monkeypatch):
    module = scheduler()
    instant = datetime(2026, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'now', lambda: instant)
    decision = advance(app, job)
    first = children(app, job)[0]
    assert first.started_at is None and first.deadline is None
    instant += timedelta(days=3)
    assert advance(app, job).cancel is False
    remote = {'process': {'state': 'running', 'child_id': first.id,
              'launch_token': decision.payload['launch_token'], 'pid': 10, 'start_time': '900',
              'started_at': instant.isoformat()}, 'cursor_before': decision.cursor}
    with app.state.session_factory.begin() as db:
        module.record_observation(db, job, first.id, remote)
    first = children(app, job)[0]
    assert first.deadline == instant + timedelta(minutes=1440)
    instant = first.deadline
    assert advance(app, job).cancel is True
    instant += timedelta(seconds=599)
    assert advance(app, job).action == 'poll'
    instant += timedelta(seconds=1)
    assert advance(app, job).action == 'done'
    first, second = children(app, job)
    assert first.state == 'needs_attention' and second.state == 'not_run'
    assert held(app, job)


def test_cancel_before_launch_has_zero_remote_side_effects(app, job):
    with app.state.session_factory.begin() as db:
        db.get(FunctionalRun, job).cancel_requested = True
    assert advance(app, job).action == 'done'
    assert all(child.launch_attempted_at is None for child in children(app, job))
    assert not held(app, job)


def test_sequential_retry_final_counts_and_leases_held_between_children(app, job, tmp_path):
    first = advance(app, job)
    assert first.action == 'launch'
    assert advance(app, job).action == 'poll'
    ingest(app, job, first, finished(first, retry=True), tmp_path)
    assert children(app, job)[0].result['case_counts']['passed'] == 1
    assert len(children(app, job)[0].result['attempt_records']) == 2
    assert held(app, job)
    second = advance(app, job)
    assert second.action == 'launch' and second.child_id != first.child_id
    assert all(lease.depth == 1 for lease in held(app, job))
    ingest(app, job, second, finished(second), tmp_path)
    assert advance(app, job).action == 'done'
    assert not held(app, job)
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, job).state == 'success'


def test_cursor_and_events_commit_together_and_duplicate_poll_is_harmless(app, job, tmp_path):
    decision = advance(app, job)
    remote = finished(decision)
    ingest(app, job, decision, remote, tmp_path)
    ingest(app, job, decision, remote, tmp_path)
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(FunctionalEvent).where(FunctionalEvent.child_id == decision.child_id)))
        assert len(rows) == 3
        child = db.get(FunctionalModuleRun, decision.child_id)
        assert child.remote_identity['cursor']['last_event']['seq'] == 3


def test_queued_cancel_does_not_wait_for_other_owners_lease(app, job):
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    with app.state.session_factory.begin() as db:
        parent = db.get(FunctionalRun, job)
        parent.cancel_requested = True
        acquire_leases(db, 'other', [LeaseRequest('cluster:' + parent.cluster_id)])
    assert advance(app, job).action == 'done'
    assert not held(app, job)


def test_confirmed_supervisor_zero_start_cancel_releases_without_process(app, job):
    decision = advance(app, job)
    with app.state.session_factory.begin() as db:
        db.get(FunctionalRun, job).cancel_requested = True
        scheduler().record_observation(db, job, decision.child_id, {
            'zero_start': {'child_id': decision.child_id, 'launch_token': decision.payload['launch_token']},
            'cursor_before': {}})
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, job).state == 'cancelled'
    assert not held(app, job)


def test_journal_mismatch_cannot_release_passing_child(app, job, tmp_path):
    decision = advance(app, job)
    remote = finished(decision)
    remote['journal_verified'] = False
    ingest(app, job, decision, remote, tmp_path)
    assert children(app, job)[0].state == 'needs_attention'
    assert held(app, job)


def test_ordinary_case_failure_can_continue_but_parent_remains_failed(app, job, tmp_path):
    first = advance(app, job)
    ingest(app, job, first, finished(first, failed=True), tmp_path)
    second = advance(app, job)
    assert second.action == 'launch'
    ingest(app, job, second, finished(second), tmp_path)
    assert advance(app, job).action == 'done'
    with app.state.session_factory() as db:
        assert db.get(FunctionalRun, job).state == 'failed'
    assert not held(app, job)


def test_parallel_workers_dispatch_only_one_child(app, job):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(lambda _: advance(app, job), range(2)))
    assert sorted(d.action for d in decisions) == ['launch', 'poll']
    assert decisions[0].child_id == decisions[1].child_id


def test_same_machine_sibling_alias_does_not_expand_child_execution_routes(app, ready, monkeypatch, tmp_path):
    module = scheduler()
    ready[2]['env1']['targets'] = [{'role': 'client', 'host': '192.0.2.1', 'user': 'test', 'mutates': True}]
    ready[2]['env2']['targets'] = [{'role': 'client', 'host': 'node1.test', 'user': 'test', 'mutates': True}]
    from dingofs_platform.inventory.models import Cluster, Machine
    with app.state.session_factory.begin() as db:
        machine = db.get(Machine, db.get(Cluster, ready[0]['cluster_id']).management_machine_id)
        machine.address = '192.0.2.1'
        machine.aliases = ['node1.test']
        actor = db.scalar(select(User).where(User.username == 'admin'))
        routes = [dict(source_host=host, machine_id=machine.id, machine_name=machine.name,
                       address=machine.address, port=machine.ssh_port, user=machine.ssh_user)
                  for host in ('192.0.2.1', 'node1.test')]
        binding = {'immutable_path': '/opt/dtt/pinned/dtt', 'functional_runtime': {'version': 2},
                   'approved_targets': [], 'resolved_targets': routes,
                   'control_connection': [machine.address, machine.ssh_port, machine.ssh_user]}
        job = create_run(db, actor, normalize(ready), runtime_binding=binding).id
    monkeypatch.setattr(module, 'revalidate_binding', lambda *args, **kwargs: binding)
    first = advance(app, job)
    outcome = finished(first)
    outcome['events'][-1]['data']['execution_targets'] = [routes[0]]
    ingest(app, job, first, outcome, tmp_path)
    assert children(app, job)[0].state == 'success'
    assert advance(app, job).action == 'launch'


def test_scheduler_persists_all_12000_events_before_terminal_evaluation(app, job, tmp_path):
    from dingofs_platform.functional.event_reader import read_events
    from sqlalchemy import func
    decision = advance(app, job)
    remote = finished(decision)
    rows = [dict(version=2, seq=i, time='2026-11-10T00:00:00Z', type='stage_started', stage='setup',
                 parent_id=job, child_id=decision.child_id, module='quota', case_path=None, attempt=None, data={})
            for i in range(1, 12001)]
    for index, event in enumerate(remote.pop('events'), 12001):
        rows.append({**event, 'seq': index})
    path = tmp_path / 'events'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    cursor = {}
    while True:
        batch = read_events(path, cursor.get('offset', 0), file_identity=cursor.get('file_identity'),
                            last_event=cursor.get('last_event'))
        more = batch.new_offset < path.stat().st_size
        with app.state.session_factory.begin() as db:
            scheduler().record_observation(db, job, decision.child_id, {**remote,
                'cursor_before': cursor, 'event_batch': asdict(batch), 'has_more': more})
        cursor = {'offset': batch.new_offset, 'file_identity': batch.file_identity, 'last_event': batch.last_event}
        if not more: break
        assert children(app, job)[0].state != 'success'
        assert advance(app, job).action == 'poll'
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FunctionalEvent)) == 12003
    assert children(app, job)[0].state == 'success'


def test_existing_child_still_monitored_when_creation_gate_is_disabled(app, job):
    decision = advance(app, job)
    polled = []
    class Fake:
        def __init__(self, config): pass
        def poll_child(self, payload, cursor, cancel=False):
            polled.append(payload['child_id'])
            return {'missing': True, 'cursor_before': cursor}
        def start_child(self, payload): raise AssertionError('must never relaunch')
    app.state.functional_transport = Fake
    app.state.settings.functional_guided_enabled = False
    app.state.functional_manager.process(job)
    assert polled == [decision.child_id]


def test_unknown_unowned_ledger_entry_blocks_next_child(app, job, tmp_path):
    first = advance(app, job)
    remote = finished(first)
    resource = dict(id='preexisting', kind='cache', cluster='cluster', host='host', user='test',
                    name='member', path=None, port=1234, owned=False, phase='unknown',
                    remote_identity={'member_id': 'member'})
    event = {**remote['events'][0], 'type': 'resource_changed', 'case_path': None, 'attempt': None,
             'data': {'resource': resource}}
    remote['events'] = [event, *remote['events']]
    for index, row in enumerate(remote['events'], 1): row['seq'] = index
    remote['events'][-1]['data']['retained_resources'] = [resource]
    ingest(app, job, first, remote, tmp_path)
    assert children(app, job)[0].state == 'needs_attention'
    assert advance(app, job).action == 'done'
    assert held(app, job)


def test_corrupt_live_stream_requests_safe_cancel_and_retains_error(app, job):
    decision = advance(app, job)
    process = {'state': 'running', 'child_id': decision.child_id, 'launch_token': decision.payload['launch_token'],
               'pid': 10, 'start_time': '12345', 'started_at': datetime.now(timezone.utc).isoformat()}
    with app.state.session_factory.begin() as db:
        scheduler().record_observation(db, job, decision.child_id,
            {'process': process, 'cursor_before': {}, 'protocol_error': 'truncated'})
    next_poll = advance(app, job)
    assert next_poll.action == 'poll' and next_poll.cancel
    with app.state.session_factory.begin() as db:
        scheduler().record_observation(db, job, decision.child_id, {'process': process, 'cursor_before': {}})
    assert children(app, job)[0].remote_identity['protocol_error'] == 'truncated'
    assert held(app, job)


def test_attempted_supervisor_without_process_identity_stays_unknown(app, job):
    decision = advance(app, job)
    with app.state.session_factory.begin() as db:
        scheduler().record_observation(db, job, decision.child_id, {'state': 'unknown', 'cursor_before': {}})
    child = children(app, job)[0]
    assert child.state == 'unknown' and child.result['child_state'] == 'unknown'
    assert advance(app, job).action == 'poll'
    assert held(app, job)
