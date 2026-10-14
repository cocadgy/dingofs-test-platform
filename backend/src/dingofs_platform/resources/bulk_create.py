"""Expand reusable instance templates; preserve per-instance execution evidence."""
from copy import deepcopy
from .models import ManagedResource


def validate_cache_count(members, count):
    if type(count) is not int or count < 1:
        raise ValueError('count: 数量必须为正整数')
    if count > 1 and any(m.get('member_id') for m in members):
        raise ValueError('count: 批量创建时请将成员 ID 留空，由平台为各实例生成')


def expand_cache_members(members, count):
    validate_cache_count(members, count)
    return [dict(deepcopy(member), **({'port_mode': 'auto'} if count > 1 else {}))
            for member in members for _ in range(count)]


def mount_instances(parameters):
    count = parameters.get('count', 1)
    children = []
    for i in range(count):
        child = deepcopy(parameters)
        child.pop('count', None)
        if count > 1:
            child['mount_path'] = parameters['mount_path'].rstrip('/') + f'-{i + 1:03d}'
        children.append(child)
    return children


def finish_mount_batch(db, op):
    """Never overwrite successful siblings when a later step fails/expires."""
    if op.action in ("mount.unmount", "mount.delete") and op.state != "succeeded":
        # An interrupted in-flight request may have changed the remote mount.
        # Completed siblings and steps not yet dispatched retain their state.
        results = (op.result or {}).get("steps", [])
        if op.cursor < len(op.steps) and op.cursor >= len(results):
            work = op.steps[op.cursor]
            if work.get("mount_batch"):
                resource = db.get(ManagedResource, work["resource_id"])
                if resource:
                    resource.state = "unknown"
                    resource.revision += 1
        return
    if op.action != 'mount.create' or op.parameters.get('count', 1) <= 1:
        return
    for index, work in enumerate(op.steps):
        resource = db.get(ManagedResource, work.get('resource_id'))
        if not resource or resource.state != 'pending':
            continue
        resource.state = 'unknown' if index == op.cursor and op.state != 'succeeded' else 'not_started'
        resource.revision += 1
