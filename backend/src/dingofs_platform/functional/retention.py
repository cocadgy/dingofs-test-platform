"""Read-only residual verification against exact server journal identities."""

TARGET_FIELDS = ('cluster', 'host', 'user', 'name', 'path', 'port')


def resource_request(row):
    return {'child_id': row.child_id, 'resource_id': row.resource_id, 'kind': row.kind,
            'expected_identity': row.remote_identity,
            'target': {key: getattr(row, key) for key in TARGET_FIELDS}}


def checked_resource_phase(row, observed):
    if not isinstance(observed, dict) or not row.remote_identity:
        return 'unknown'
    if any(observed.get(key) != value for key, value in resource_request(row).items()):
        return 'unknown'
    if row.kind not in ('filesystem', 'directory', 'mount', 'cache'):
        return 'unknown'
    # A missing mount may hide filesystem-relative directories. Without full
    # dependency identity checks, local path absence says nothing about cleanup.
    if row.kind == 'directory' and row.remote_identity.get('filesystem_relative'):
        return 'unknown'
    if observed.get('status') == 'absent' and observed.get('identity') is None:
        return 'removed' if row.owned else 'unknown'
    if observed.get('status') == 'present' and observed.get('identity') == row.remote_identity:
        return 'retained' if row.owned else 'active'
    if (row.kind == 'cache' and row.owned and observed.get('status') == 'present'
            and observed.get('identity') == {**row.remote_identity, 'process': None}):
        return 'retained'  # Registration still exists; process exit is not cleanup.
    return 'unknown'


def child_ended(child):
    if child.state == 'not_run' and child.launch_attempted_at is None and not child.remote_identity:
        return True
    if child.state in ('queued', 'running', 'cancelling', 'unknown'):
        return False
    identity = child.remote_identity or {}
    state = identity.get('remote_state', {})
    process, proof = state.get('process', {}), state.get('end_proof', {})
    return bool(process.get('state') == 'exited' and process.get('child_id') == child.id
        and process.get('launch_token') and process.get('launch_token') == identity.get('launch_token')
        and type(process.get('pid')) is int and process['pid'] > 0 and process.get('start_time')
        and type(state.get('returncode')) is int and proof.get('returncode') == state['returncode']
        and all(process.get(key) == proof.get(key) for key in ('child_id', 'launch_token', 'pid', 'start_time')))


def probe_resource(db, actor, parent, child, resource):
    from pathlib import Path
    import time
    from dingofs_platform.errors import Problem
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.permissions import require_manage
    from dingofs_platform.inventory.credentials import decrypt_password
    from dingofs_platform.inventory.ssh_transport import SSHConfig
    from dingofs_platform.tool_packages.ssh_session import Remote
    from . import retention_probe
    routes = [route for route in parent.snapshot.get('runtime_binding', {}).get('resolved_targets', [])
              if resource.host in (route['source_host'], route['address']) and resource.user == route['user']]
    if len(routes) != 1:
        raise Problem(409, 'retention_target_changed', '残留资源目标身份不完整')
    route = routes[0]
    machine = db.get(Machine, route['machine_id'])
    if not machine or machine.archived:
        raise Problem(409, 'retention_target_changed', '残留资源机器不可用')
    require_manage(actor, machine)
    if [machine.address, machine.ssh_port, machine.ssh_user] != [route['address'], route['port'], route['user']]:
        raise Problem(409, 'retention_target_changed', '残留资源连接身份已改变')
    if set(resource.cluster.split(',')) != set(child.environment_snapshot['mds_addresses']):
        raise Problem(409, 'retention_target_changed', '残留资源集群身份不一致')
    settings = db.info['functional_settings']
    config = SSHConfig(machine.address, machine.ssh_port, machine.ssh_user,
        decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key))
    payload = {**resource_request(resource), 'dingo': child.environment_snapshot.get('programs', {}).get('dingo') or '/usr/local/bin/dingo'}
    transport = db.info.get('functional_retention_transport')
    def invoke(connection, request, function):
        code = 'REQUEST=' + repr(request) + '\n' + Path(retention_probe.__file__).read_text() + '\nprint(json.dumps(' + function + '(REQUEST)))\n'
        if transport:
            return transport(connection, code)
        remote = Remote(connection, time.monotonic() + 60, lambda **kw: None, '残留资源复核')
        try:
            return remote.python(code, '读取精确资源身份', max_bytes=1024 * 1024)
        finally:
            remote.close()
    if resource.kind == 'cache':
        binding = parent.snapshot.get('runtime_binding', {})
        control = db.get(Machine, binding.get('machine_id'))
        if (not control or control.archived
                or [control.address, control.ssh_port, control.ssh_user] != binding.get('control_connection')):
            raise Problem(409, 'retention_target_changed', '原始控制连接身份已改变')
        require_manage(actor, control)
        control_config = SSHConfig(control.address, control.ssh_port, control.ssh_user,
            decrypt_password(control.ssh_password_ciphertext, settings.credential_encryption_key))
        payload['registration'] = invoke(control_config, payload, 'cache_registration')
    return invoke(config, payload, 'probe')


def cleanup_operation_ended(op):
    if op.state == 'succeeded':
        return True
    if op.state != 'failed':
        return False
    result = op.result or {}
    return result.get('zero_start') is True or bool(result.get('steps') and
        all(step.get('remote_ended') is True for step in result['steps']))


def cleanup_in_progress(db, run_id):
    from sqlalchemy import select
    from dingofs_platform.resources.models import ResourceOperation
    operations = list(db.scalars(select(ResourceOperation)))
    related = {op.id for op in operations if op.parameters.get('_functional_cleanup', {}).get('run_id') == run_id}
    while True:
        descendants = {op.id for op in operations if op.parameters.get('retry_operation_id') in related}
        if descendants <= related:
            break
        related.update(descendants)
    return any(op.id in related and not cleanup_operation_ended(op) for op in operations)


def verify_retained_resources(db, actor, run_id):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from dingofs_platform.errors import Problem
    from dingofs_platform.inventory.permissions import require_manage
    from dingofs_platform.operations.models import OperationLease
    from dingofs_platform.operations.leases import LeaseRequest, lock_keys, release_verified, VerificationEvidence
    from .models import FunctionalRun, FunctionalModuleRun, FunctionalResource, ACTIVE
    parent = db.get(FunctionalRun, run_id)
    if not parent or parent.version != 2:
        raise Problem(404, 'not_found', '引导任务不存在')
    require_manage(actor, parent)
    owner = 'functional:' + run_id
    keys = frozenset(db.scalars(select(OperationLease.key).where(OperationLease.owner == owner,
                                 OperationLease.released_at.is_(None))))
    lock_keys(db, [LeaseRequest(key) for key in keys])
    db.refresh(parent, with_for_update=True)
    children = list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id)
                    .order_by(FunctionalModuleRun.position).with_for_update()))
    if parent.state in ACTIVE or not parent.finished_at or not children or not all(child_ended(c) for c in children):
        raise Problem(409, 'retention_end_unverified', '任务远端结束尚未验证，不能释放资源')
    if cleanup_in_progress(db, run_id):
        raise Problem(409, 'retention_cleanup_active', '关联清理操作尚未确认结束，不能释放资源')
    by_id = {child.id: child for child in children}
    resources = list(db.scalars(select(FunctionalResource).where(FunctionalResource.child_id.in_(by_id)).with_for_update()))
    for resource in resources:
        if resource.phase == 'removed':
            continue  # An authoritative persisted removal is already verified.
        try:
            observed = probe_resource(db, actor, parent, by_id[resource.child_id], resource)
            resource.phase = checked_resource_phase(resource, observed)
        except Exception:
            resource.phase = 'unknown'
    unresolved = any(r.phase in ('intent', 'retained', 'unknown') or r.owned and r.phase == 'active' for r in resources)
    recovery_ok = all((c.state == 'not_run' and c.launch_attempted_at is None) or
                      c.result.get('recovery_status') in ('recovered', 'not_required') for c in children)
    evidence = VerificationEvidence(owner, True, recovery_ok, keys,
        keys if unresolved or not recovery_ok else frozenset(), datetime.now(timezone.utc))
    db.flush()
    release_verified(db, owner, evidence)
    return evidence
