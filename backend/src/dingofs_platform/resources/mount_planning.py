"""Immutable multi-machine mount plans; every client owns its lifecycle record."""
from copy import deepcopy
from datetime import timedelta
from dingofs_platform.errors import Problem
from .models import ManagedResource, ResourceOperation
from .views import now
from .bulk_create import mount_instances


def expand_clients(parameters):
    clients, seen = [], set()
    for row in parameters['clients']:
        for index, child in enumerate(mount_instances(row)):
            child['count'] = 1
            identity = child['machine_id'], child['mount_path']
            if identity in seen:
                raise ValueError('同一机器的挂载路径不能重复')
            seen.add(identity)
            if row.get('count', 1) > 1 and child.get('mount_options', {}).get('cache_dir'):
                child['mount_options']['cache_dir'] = child['mount_options']['cache_dir'].rstrip('/') + f'-{index + 1:03d}'
            clients.append(child)
    return clients


def prepare(db, actor, cluster, parameters):
    from .service import prepare as prepare_resource
    from dingofs_platform.mount_profiles import service as profiles
    work = []
    try:
        clients = expand_clients(parameters)
    except ValueError as exc:
        raise Problem(422, 'invalid_parameters', str(exc)) from None
    for index, client in enumerate(clients):
        if client.get('mount_profile_id'):
            # Validate the selected revision even when explicit options override it.
            profiles.resolve(db, client['mount_profile_id'], client['mount_profile_revision'])
        steps, resource = prepare_resource(db, actor, cluster, 'mount.create', client)
        data = deepcopy(resource.data)
        data.setdefault('mount_options', {}).setdefault('cache_dir', data['state_dir'] + '/cache')
        resource.data = data
        resource.state = 'planned'
        for item in steps:
            item.update(action='mount.plan', resource_id=resource.id, batch_index=index + 1, record=deepcopy(data))
        work.extend(steps)
    return work, None


def consume(db, actor, cluster, operation_id, *, retry=False):
    from .execution import valid
    previous = db.get(ResourceOperation, operation_id)
    expected = 'mount.create' if retry else 'mount.plan'
    states = ('failed', 'interrupted', 'cancelled', 'unknown') if retry else ('succeeded',)
    if (not previous or previous.action != expected or previous.actor_id != actor.id
            or previous.cluster_id != cluster.id or previous.state not in states or not valid(db, previous)):
        raise Problem(409, 'mount_plan_invalid', '挂载任务失效，请重新检查')
    if not retry and previous.expires_at <= now():
        raise Problem(409, 'mount_plan_expired', '挂载检查已过期，请重新检查')
    work = []
    for original in previous.steps:
        resource = db.get(ManagedResource, original.get('resource_id'))
        if not resource:
            raise Problem(409, 'mount_resource_missing', '客户端记录已不存在')
        if retry and resource.state == 'mounted':
            continue
        allowed = ('unknown', 'not_started') if retry else ('planned',)
        if resource.state not in allowed:
            raise Problem(409, 'mount_plan_consumed', '客户端状态已变化，请查看原任务并重新检查')
        item = deepcopy(original)
        item.update(action='mount.create', record=deepcopy(resource.data))
        resource.state = 'pending'
        work.append(item)
    if not work:
        raise Problem(409, 'mount_retry_empty', '没有需要重试的客户端')
    return work, None


def store_check(db, op, cursor, data):
    info = data.get('binary_info')
    if not isinstance(info, dict) or not str(info.get('path', '')).startswith('/') or len(info.get('sha256', '')) != 64:
        raise ValueError('挂载程序检查没有返回有效路径与校验值')
    steps = deepcopy(op.steps)
    port = data.get('effective_port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('挂载检查没有返回有效端口')
    steps[cursor]['record']['binary_info'] = info
    steps[cursor]['record']['checked_port'] = port
    op.steps = steps
    resource = db.get(ManagedResource, steps[cursor]['resource_id'])
    resource.data = {**resource.data, 'binary_info': info, 'checked_port': port}


def finish(db, op, state):
    if op.action == 'mount.plan' and state == 'succeeded':
        op.expires_at = now() + timedelta(minutes=10)
