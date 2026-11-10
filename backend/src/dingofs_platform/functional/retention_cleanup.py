"""Narrow, server-only exceptions for confirmed single-resource management cleanup."""
from copy import deepcopy

ALLOWED_ACTIONS = frozenset(('fs.delete', 'mount.unmount', 'cache.stop', 'cache.delete'))


def lock_cleanup_owner(db, context):
    """Take the entire functional lease union before any business-row locks."""
    from sqlalchemy import select
    from dingofs_platform.operations.models import OperationLease
    from dingofs_platform.operations.leases import lock_keys, LeaseRequest
    from dingofs_platform.auth.users import lock_accounts
    lock_accounts(db)
    keys = list(db.scalars(select(OperationLease.key).where(
        OperationLease.owner == 'functional:' + context['run_id'], OperationLease.released_at.is_(None))))
    lock_keys(db, [LeaseRequest(key) for key in keys])


def control_step_matches(work, binding):
    connection = binding.get('control_connection') or []
    return (len(connection) == 3 and work.get('machine_id') == binding.get('machine_id')
            and work.get('machine_address') == connection[0] and work.get('target_user') == connection[2])


def validate_control_steps(db, actor, steps, binding):
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.permissions import require_manage
    for work in steps:
        if work['action'] not in ('cache.verify_members', 'cache.delete'):
            continue
        machine = db.get(Machine, work['machine_id'])
        if (not control_step_matches(work, binding) or not machine or machine.archived
                or [machine.address, machine.ssh_port, machine.ssh_user] != binding.get('control_connection')):
            return False
        require_manage(actor, machine)
    return True


def matches_cleanup_step(resource, work, routes, *, binding=None, namespace=None, boot_id=None):
    if (work.get('action') not in ALLOWED_ACTIONS | {'cache.stop_external', 'mount.unmount_discovered'}
            or set(work.get('mds_addr', '').split(',')) != set(resource.cluster.split(','))):
        return False
    matches = [r for r in routes if resource.host in (r['source_host'], r['address'])
               and resource.user == r['user']]
    if len(matches) != 1:
        return False
    record, parameters = work.get('record') or {}, work.get('parameters') or {}
    if resource.kind == 'cache' and work['action'] == 'cache.delete':
        return bool(binding and control_step_matches(work, binding) and parameters == {'member_id': resource.name})
    route = matches[0]
    if route['machine_id'] != work.get('machine_id') or route['address'] != work.get('machine_address'):
        return False
    original_user = work.get('target_user') == resource.user
    identity = resource.remote_identity
    if work.get('target_user') == 'root' and resource.kind == 'mount' and record.get('origin') == 'external':
        saved, process = record.get('identity') or {}, identity.get('process') or {}
        original_user = bool(work['action'] == 'mount.unmount' and record.get('client_user') == resource.user
            and namespace and saved.get('namespace') == namespace and str(saved.get('mount_id')) == str(identity.get('id'))
            and process.get('pid') and saved.get('pid') == process['pid']
            and saved.get('start_ticks') == process.get('start_time') and saved.get('exe') == process.get('exe'))
    if resource.kind == 'cache' and work['action'] == 'cache.stop_external':
        return bool(work.get('target_user') == 'root' and parameters == {'member_id': resource.name}
            and record.get('member_id') == resource.name and record.get('group_name') == identity.get('group_name')
            and record.get('listen_ip') == identity.get('ip')
            and record.get('listen_port') == resource.port == identity.get('port'))
    if not original_user:
        return False
    if resource.kind == 'filesystem' and work['action'] == 'fs.delete':
        return parameters == {'fs_name': resource.name}
    if resource.kind == 'mount' and work['action'] == 'mount.unmount':
        return record.get('mount_path') == resource.path and record.get('fs_name') == resource.name
    if resource.kind == 'cache' and work['action'] == 'cache.stop':
        return record.get('member_id') == resource.name and record.get('listen_port') == resource.port
    return False


def _authorize(db, actor, parent, child, resource, work, requests, *, mount_scope=None, operation_id=None):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from dingofs_platform.inventory.permissions import require_manage
    from dingofs_platform.operations.models import OperationLease
    from dingofs_platform.operations.leases import (check_conflicts, VerificationEvidence,
        authorize_retained_cleanup)
    from .models import FunctionalModuleRun
    from . import retention
    require_manage(actor, parent)
    children = list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == parent.id)))
    if not children or not all(retention.child_ended(c) for c in children):
        return False
    binding = parent.snapshot.get('runtime_binding', {})
    owner = 'functional:' + parent.id
    keys = frozenset(db.scalars(select(OperationLease.key).where(OperationLease.owner == owner,
                                 OperationLease.released_at.is_(None))))
    if not {r.key for r in requests} <= keys or check_conflicts(db, requests, owner):
        return False
    if retention.cleanup_in_progress(db, parent.id, child_id=child.id, resource_id=resource.resource_id,
                                     exclude_operation_id=operation_id):
        return False
    observed = retention.probe_resource(db, actor, parent, child, resource)
    if resource.kind == 'mount':
        current_scope = {key: observed.get(key) for key in ('namespace', 'boot_id')}
        if (not all(isinstance(value, str) and value for value in current_scope.values())
                or observed.get('process_namespace') != current_scope['namespace']
                or mount_scope is not None and mount_scope != current_scope):
            return False
    if not matches_cleanup_step(resource, work, binding.get('resolved_targets', []), binding=binding,
                                namespace=observed.get('namespace'), boot_id=observed.get('boot_id')):
        return False
    # Command-host identity is separate from the original resource owner/host.
    from dingofs_platform.inventory.models import Machine
    command = db.get(Machine, work['machine_id'])
    if not command or command.archived or command.address != work['machine_address']:
        return False
    require_manage(actor, command)
    if work['action'] == 'cache.delete' and [command.address, command.ssh_port, command.ssh_user] != binding.get('control_connection'):
        return False
    identity_matches = observed.get('identity') == resource.remote_identity
    if resource.kind == 'cache' and work['action'] == 'cache.delete':
        from dingofs_platform.resources.models import ResourceOperation
        stopped = [op for op in db.scalars(select(ResourceOperation).where(ResourceOperation.state == 'succeeded',
                    ResourceOperation.action == 'cache.stop'))
                   if op.parameters.get('_functional_cleanup', {}).get('run_id') == parent.id
                   and op.parameters['_functional_cleanup'].get('child_id') == child.id
                   and op.parameters['_functional_cleanup'].get('resource_id') == resource.resource_id
                   and op.parameters['_functional_cleanup'].get('identity') == resource.remote_identity]
        identity_matches = bool(stopped and observed.get('identity') == {**resource.remote_identity, 'process': None})
    if retention.checked_resource_phase(resource, observed) != 'retained' or not identity_matches:
        return False
    evidence = VerificationEvidence(owner, True, False, frozenset(), keys, datetime.now(timezone.utc))
    authorize_retained_cleanup(db, owner, evidence, child_id=child.id, resource_id=resource.resource_id,
        kind=resource.kind, remote_identity=resource.remote_identity,
        target={key: getattr(resource, key) for key in retention.TARGET_FIELDS})
    return observed


def resolve_cleanup_exception(db, actor, cluster, action, parameters, requests):
    """Return a server-only context only for one uniquely matching retained object."""
    from sqlalchemy import select
    from dingofs_platform.errors import Problem
    from dingofs_platform.operations.leases import check_conflicts, lock_keys, LeaseRequest
    from dingofs_platform.operations.models import OperationLease
    from dingofs_platform.resources.service import prepare
    from .models import FunctionalRun, FunctionalModuleRun, FunctionalResource
    if action not in ALLOWED_ACTIONS or {'resource_ids', 'targets'} & parameters.keys():
        return None
    conflicts = check_conflicts(db, requests)
    owners = {c.owner for c in conflicts}
    if len(owners) != 1 or not next(iter(owners)).startswith('functional:'):
        return None
    owner = next(iter(owners))
    keys = list(db.scalars(select(OperationLease.key).where(OperationLease.owner == owner,
                           OperationLease.released_at.is_(None))))
    lock_keys(db, [LeaseRequest(key) for key in keys])
    parent = db.get(FunctionalRun, owner.removeprefix('functional:'))
    if not parent or parent.cluster_id != cluster.id or parent.version != 2:
        return None
    try:
        steps, managed_resource = prepare(db, actor, cluster, action, parameters)
        binding = parent.snapshot.get('runtime_binding', {})
        steps = [{**step, 'mds_addr': ','.join((cluster.status_snapshot or {}).get('mds_addresses', []))} for step in steps]
        # External single-member stop has one read-only registration check first.
        if (len(steps) == 2 and action == 'cache.stop' and steps[0]['action'] == 'cache.verify_members'
                and steps[1]['action'] == 'cache.stop_external'):
            verify, step = steps
            member = step['parameters'].get('member_id')
            expected = {key: value for key, value in step['record'].items() if key != 'force_stop'}
            if (not control_step_matches(verify, binding) or verify['parameters'] != {'member_ids': [member]}
                    or verify['record'] != {'members': [expected]}):
                return None
        elif len(steps) == 1 and steps[0]['action'] in ({action} | ({'mount.unmount_discovered'} if action == 'mount.unmount' else set())):
            step = steps[0]
        else:
            return None
        if not validate_control_steps(db, actor, steps, binding):
            return None
        resources = list(db.scalars(select(FunctionalResource).join(FunctionalModuleRun,
            FunctionalResource.child_id == FunctionalModuleRun.id).where(FunctionalModuleRun.run_id == parent.id,
            FunctionalResource.owned.is_(True), FunctionalResource.phase == 'retained')))
        routes = binding.get('resolved_targets', [])
        record = step.get('record') or {}
        namespace = (record.get('identity') or {}).get('namespace') or record.get('namespace')
        matches = [r for r in resources if matches_cleanup_step(r, step, routes, binding=binding,
                      namespace=namespace, boot_id=record.get('boot_id'))]
        if len(matches) != 1:
            return None
        resource = matches[0]
        child = db.get(FunctionalModuleRun, resource.child_id)
        observed = _authorize(db, actor, parent, child, resource, step, requests)
        if not observed:
            return None
        context = {'run_id': parent.id, 'child_id': child.id, 'resource_id': resource.resource_id,
                   'kind': resource.kind, 'identity': deepcopy(resource.remote_identity), 'step': deepcopy(step),
                   'target': {key: getattr(resource, key) for key in ('cluster', 'host', 'user', 'name', 'path', 'port')},
                   'steps': deepcopy(steps), 'managed_resource_id': managed_resource.id if managed_resource else None}
        if resource.kind == 'mount':
            context['mount_scope'] = {key: observed[key] for key in ('namespace', 'boot_id')}
        return context, steps
    except Exception:
        return None


def revalidate_cleanup_exception(db, actor, context, steps, requests, *, operation_id=None):
    from sqlalchemy import select
    from dingofs_platform.errors import Problem
    from .models import FunctionalRun, FunctionalModuleRun, FunctionalResource
    try:
        if operation_id is not None:
            from dingofs_platform.resources.models import ResourceOperation
            operation = db.get(ResourceOperation, operation_id)
            if not operation or operation.parameters.get('_functional_cleanup') != context or operation.steps != steps:
                raise ValueError('cleanup operation changed')
        parent = db.get(FunctionalRun, context['run_id'])
        child = db.get(FunctionalModuleRun, context['child_id'])
        resource = db.scalar(select(FunctionalResource).where(FunctionalResource.child_id == context['child_id'],
                             FunctionalResource.resource_id == context['resource_id']))
        if (not parent or not child or not resource or child.run_id != parent.id
                or resource.kind != context['kind'] or resource.remote_identity != context['identity']
                or context.get('target') != {key: getattr(resource, key) for key in ('cluster', 'host', 'user', 'name', 'path', 'port')}
                or steps != context['steps'] or steps[-1] != context['step']
                or not validate_control_steps(db, actor, steps, parent.snapshot.get('runtime_binding', {}))
                or resource.kind == 'mount' and not context.get('mount_scope')
                or not _authorize(db, actor, parent, child, resource, steps[-1], requests,
                                  mount_scope=context.get('mount_scope'), operation_id=operation_id)):
            raise ValueError('cleanup identity changed')
    except Exception:
        raise Problem(409, 'cleanup_not_verified', '残留清理目标或身份已改变，请重新复核') from None
