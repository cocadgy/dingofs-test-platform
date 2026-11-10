"""Durable platform-operation coordination; this cannot lock external Jenkins.

Transactions belong to callers. Lock order is the existing accounts lock, then
sorted lease keys, then inventory/business rows. Never acquire a new lease key
after taking an inventory or business row lock. No heartbeat/TTL reclaims work.
VerificationEvidence is an internal worker result, never an HTTP input schema.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Literal

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from dingofs_platform.auth.users import lock_accounts
from dingofs_platform.errors import Problem
from .models import OperationLease


@dataclass(frozen=True)
class LeaseRequest:
    key: str
    mode: Literal['shared', 'exclusive'] = 'exclusive'

    def __post_init__(self):
        if not self.key or len(self.key) > 512 or self.mode not in ('shared', 'exclusive'):
            raise ValueError('invalid lease request')


@dataclass(frozen=True)
class Conflict:
    key: str
    owner: str
    mode: str
    reason: str = 'incompatible_lease'


@dataclass(frozen=True)
class LeaseDecision:
    acquired: bool
    conflicts: tuple[Conflict, ...] = ()


@dataclass(frozen=True)
class VerificationEvidence:
    owner: str
    remote_ended: bool
    recovery_ok: bool
    verified_resources: frozenset[str]
    remaining_resources: frozenset[str]
    observed_at: datetime


def _requests(requests):
    modes = {}
    for request in requests:
        if modes.get(request.key) != 'exclusive':
            modes[request.key] = request.mode
    return [LeaseRequest(key, modes[key]) for key in sorted(modes)]


def advisory_key(key: str) -> int:
    return int.from_bytes(hashlib.sha256(('dingofs-operation-lease:' + key).encode()).digest()[:8],
                          'big', signed=True)


def lock_keys(db: Session, requests: list[LeaseRequest]) -> None:
    if not requests:
        return
    lock_accounts(db)
    for request in _requests(requests):
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': advisory_key(request.key)})


def check_conflicts(db: Session, requests: list[LeaseRequest], owner: str | None = None) -> list[Conflict]:
    requests = _requests(requests)
    lock_keys(db, requests)
    modes = {request.key: request.mode for request in requests}
    rows = db.scalars(select(OperationLease).where(OperationLease.key.in_(modes),
                      OperationLease.released_at.is_(None)).order_by(OperationLease.key, OperationLease.owner))
    return [Conflict(row.key, row.owner, row.mode) for row in rows if row.owner != owner
            and (row.mode == 'exclusive' or modes[row.key] == 'exclusive')]


def require_available(db: Session, requests: list[LeaseRequest], owner: str | None = None) -> None:
    if check_conflicts(db, requests, owner):
        raise Problem(409, 'operation_conflict', '目标资源被其他操作占用或远端结果尚未确认')


def acquire_leases(db: Session, owner: str, requests: list[LeaseRequest]) -> LeaseDecision:
    if not owner or len(owner) > 128:
        raise ValueError('invalid lease owner')
    requests = _requests(requests)
    conflicts = check_conflicts(db, requests, owner)
    if conflicts:
        return LeaseDecision(False, tuple(conflicts))
    now = datetime.now(timezone.utc)
    for request in requests:
        row = db.scalar(select(OperationLease).where(OperationLease.key == request.key,
                        OperationLease.owner == owner, OperationLease.mode == request.mode))
        if row is None:
            db.add(OperationLease(key=request.key, owner=owner, mode=request.mode, acquired_at=now))
        elif row.released_at is not None:
            row.acquired_at, row.released_at, row.depth = now, None, 1
        else:
            row.depth += 1
    db.flush()
    return LeaseDecision(True)


def ensure_leases(db: Session, owner: str, requests: list[LeaseRequest]) -> LeaseDecision:
    """Monitoring/resume is idempotent; explicit acquire_leases is reentrant."""
    requests = _requests(requests)
    conflicts = check_conflicts(db, requests, owner)
    if conflicts:
        return LeaseDecision(False, tuple(conflicts))
    held = {(row.key, row.mode) for row in db.scalars(select(OperationLease).where(
        OperationLease.owner == owner, OperationLease.released_at.is_(None)))}
    missing = [r for r in requests if (r.key, r.mode) not in held and (r.key, 'exclusive') not in held]
    return acquire_leases(db, owner, missing)


def release_verified(db: Session, owner: str, evidence: VerificationEvidence) -> None:
    # An owner-completion verification releases all reentrant depth for exactly
    # these keys. A status string, elapsed deadline or worker exit is no proof.
    if (not isinstance(evidence, VerificationEvidence) or evidence.owner != owner
            or not evidence.remote_ended or not evidence.recovery_ok
            or evidence.observed_at.tzinfo is None
            or evidence.observed_at > datetime.now(timezone.utc)):
        return
    keys = evidence.verified_resources - evidence.remaining_resources
    lock_keys(db, [LeaseRequest(key) for key in keys])
    if owner.startswith('functional:'):
        from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalResource
        # Conservative owner-wide retention: a remaining ledger entry may share
        # a machine/runtime/cluster key with the resource just cleaned. Task11
        # must reverify every entry, never infer release from cleaning one path.
        # Verified pre-existing, non-owned resources remain active in place.
        parent_id = owner.removeprefix('functional:')
        parent = db.get(FunctionalRun, parent_id)
        if parent and parent.version == 2:
            if (parent.state in ('queued', 'running', 'cancelling', 'unknown') or not parent.finished_at
                    or parent.finished_at > evidence.observed_at):
                return
            if db.scalar(select(FunctionalModuleRun.id).where(FunctionalModuleRun.run_id == parent_id,
                         FunctionalModuleRun.state.in_(('queued', 'running', 'cancelling', 'unknown')))):
                return
            if db.scalar(select(FunctionalResource.id).join(FunctionalModuleRun,
                    FunctionalResource.child_id == FunctionalModuleRun.id).where(
                    FunctionalModuleRun.run_id == parent_id,
                    or_(FunctionalResource.phase.in_(('intent', 'retained', 'unknown')),
                        and_(FunctionalResource.owned.is_(True), FunctionalResource.phase == 'active')))):
                return
    rows = db.scalars(select(OperationLease).where(OperationLease.owner == owner,
                      OperationLease.key.in_(keys), OperationLease.released_at.is_(None)))
    for row in rows:
        if evidence.observed_at >= row.acquired_at:
            row.released_at = evidence.observed_at
            row.depth = 0
    db.flush()


def performance_requests(db, machine_id, target_path):
    from dingofs_platform.resources.models import ManagedResource
    requests = [LeaseRequest('machine:' + machine_id), LeaseRequest('runtime:' + machine_id, 'shared')]
    for mount in db.scalars(select(ManagedResource).where(ManagedResource.kind == 'mount',
                            ManagedResource.state != 'deleted')):
        data = mount.data
        path = data.get('mount_path') or data.get('mountpoint') or data.get('mount_point')
        if data.get('machine_id') == machine_id and path and (target_path == path or target_path.startswith(path.rstrip('/') + '/')):
            requests.append(LeaseRequest('cluster:' + mount.cluster_id))
    return _requests(requests)


def tool_requests(machine_id, action, options=None):
    if action == 'check':
        return []
    requests = [LeaseRequest('machine:' + machine_id), LeaseRequest('runtime:' + machine_id)]
    if action == 'auto_install':
        source_id = (options or {}).get('source_machine_id')
        if not source_id:
            raise Problem(422, 'source_unavailable', '工具来源机器未绑定')
        if options.get('tool') == 'dtt':
            # Docker pull/export modifies source-host image/runtime state too.
            requests.extend([LeaseRequest('machine:' + source_id), LeaseRequest('runtime:' + source_id)])
        else:
            requests.append(LeaseRequest('runtime:' + source_id, 'shared'))
    return _requests(requests)


def completion_evidence(owner, requests):
    """Only call after a worker has positively verified its remote completion."""
    return VerificationEvidence(owner, True, True, frozenset(r.key for r in requests),
                                frozenset(), datetime.now(timezone.utc))


def functional_requests(db, cluster_id, control_machine_id, descriptors, *, actor=None):
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.permissions import require_manage
    from dingofs_platform.inventory.host_identity import normalize_host
    from dingofs_platform.resources.external_cache import machine_addresses
    machines = list(db.scalars(select(Machine).where(Machine.archived == False)))
    requests = [LeaseRequest('cluster:' + cluster_id), LeaseRequest('runtime:' + control_machine_id, 'shared')]
    for descriptor in descriptors:
        for target in descriptor.get('targets', []):
            if not target.get('mutates'):
                continue
            host = normalize_host(target['host'])
            matches = [m for m in machines if host in machine_addresses(m) or host == m.name]
            if len(matches) != 1:
                raise Problem(422, 'target_unresolved', '测试写入目标必须唯一匹配已登记机器')
            if actor is not None:
                require_manage(actor, matches[0])
            requests.append(LeaseRequest('machine:' + matches[0].id))
    return _requests(requests)


def legacy_functional_requests(db, cluster_id, machine_id, snapshot, source_root=None, *, actor=None, strict=False,
                               descriptors=None, source_bound=False):
    """Resolve old requests from trusted custom settings or local source YAML.

    Bare environment names are not a declaration that only the control host is
    mutated. Such old queued requests can never launch without resolved targets.
    """
    from pathlib import Path
    from dingofs_platform.inventory.models import Machine
    if descriptors is not None:
        if strict and not source_bound:
            raise Problem(422, 'target_unresolved', '框架目标描述器尚未绑定并校验远端源版本')
        return functional_requests(db, cluster_id, machine_id, descriptors, actor=actor)
    profile = snapshot.get('environment_profile_snapshot') or {}
    if strict and profile.get('kind') != 'custom' and not (
            profile.get('kind') == 'predefined' and profile.get('source_file')
            and all(isinstance(profile.get(key), str) and len(profile[key]) == 64
                    for key in ('source_file_sha', 'storage_file_sha'))):
        raise Problem(422, 'target_unresolved', '旧任务没有绑定远端环境源版本，请重新选择并验证环境')
    targets = []
    complete = False
    if profile.get('kind') == 'custom':
        if set(snapshot.get('selected', {})) & {'fault', 'mds_manage', 'hot_upgrade', 'cache_node', 'large_scale_cache'}:
            raise Problem(422, 'target_unresolved', '特殊模块需要框架目标描述器，请使用引导预检')
        from dingofs_platform.functional.environments.service import member_machine_ids
        for mid in member_machine_ids(profile['settings'], profile['machine_id']):
            machine = db.get(Machine, mid)
            if not machine:
                raise Problem(422, 'target_unresolved', '测试写入目标机器不存在')
            targets.append({'host': machine.address, 'mutates': True})
        complete = bool(targets)
    elif source_root:
        from dingofs_platform.functional.source_bridge import inspect_source
        from dingofs_platform.functional.catalog import MODULE_DIRS
        try:
            modules = {module: [f'testcases/{MODULE_DIRS[module]}/{case}' for case in cases]
                       for module, cases in snapshot.get('selected', {}).items()}
            descriptor = inspect_source(Path(source_root).parent, snapshot.get('env_name'), modules)
        except (ValueError, KeyError):
            raise Problem(422, 'target_unresolved', '可信框架目标描述器不可用，请重新预检') from None
        if descriptor.issues or not descriptor.targets or any(not c.available for c in descriptor.modules.values()):
            raise Problem(422, 'target_unresolved', '环境或用例目标不完整，请重新预检')
        # A local source summary is never proof of the remote pinned runtime.
        return legacy_functional_requests(db, cluster_id, machine_id, snapshot, actor=actor,
            strict=strict, descriptors=[descriptor.model_dump(mode='json')], source_bound=source_bound)
    if strict and not complete:
        raise Problem(422, 'target_unresolved', '旧任务缺少可验证的写入目标，请重新选择并验证测试环境')
    return functional_requests(db, cluster_id, machine_id, [{'targets': targets}], actor=actor)


def authorize_retained_cleanup(db, owner, evidence, *, child_id, resource_id, kind, remote_identity, target):
    """Authorize only this exact server-ledger object, never a cluster-wide bypass.

    Task11 calls this after server-side remote identity verification and before
    executing the returned resource's cleanup under its original lease owner.
    It must not accept evidence/identity from the browser or substitute targets.
    A later release_verified still requires all owned/uncertain remnants to be
    resolved; verified pre-existing non-owned resources may remain in place.
    """
    from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalResource
    keys = list(db.scalars(select(OperationLease.key).where(OperationLease.owner == owner,
                          OperationLease.released_at.is_(None))))
    if not keys:
        raise Problem(409, 'cleanup_not_verified', '任务没有持有可用于清理的资源占用')
    lock_keys(db, [LeaseRequest(key) for key in keys])
    held = list(db.scalars(select(OperationLease).where(OperationLease.owner == owner,
                          OperationLease.released_at.is_(None))))
    parent = db.get(FunctionalRun, owner.removeprefix('functional:'), with_for_update=True) if owner.startswith('functional:') else None
    child = db.get(FunctionalModuleRun, child_id, with_for_update=True)
    resource = db.scalar(select(FunctionalResource).where(FunctionalResource.child_id == child_id,
                         FunctionalResource.resource_id == resource_id).with_for_update())
    active_child = db.scalar(select(FunctionalModuleRun.id).where(
        FunctionalModuleRun.run_id == parent.id,
        FunctionalModuleRun.state.in_(('queued', 'running', 'cancelling', 'unknown')))) if parent else None
    valid = (isinstance(evidence, VerificationEvidence) and evidence.owner == owner
             and held and not active_child
             and parent and parent.version == 2 and parent.finished_at and evidence.remote_ended
             and parent.state not in ('queued', 'running', 'cancelling', 'unknown')
             and child and child.run_id == parent.id and child.finished_at
             and child.state not in ('queued', 'running', 'cancelling', 'unknown')
             and evidence.observed_at.tzinfo is not None
             and max(parent.finished_at, child.finished_at) <= evidence.observed_at <= datetime.now(timezone.utc)
             and all(evidence.observed_at >= lease.acquired_at for lease in held)
             and resource and resource.owned and resource.phase == 'retained'
             and resource.kind == kind and bool(remote_identity) and resource.remote_identity == remote_identity
             and target == {key: getattr(resource, key) for key in ('cluster', 'host', 'user', 'name', 'path', 'port')})
    if not valid:
        raise Problem(409, 'cleanup_not_verified', '只能清理已确认结束任务的精确残留资源')
    return resource
