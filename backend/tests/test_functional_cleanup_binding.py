"""Exact operation-target adapters; a lease owner alone never grants cleanup."""
from types import SimpleNamespace

import pytest


def row(kind='filesystem'):
    return SimpleNamespace(kind=kind, cluster='mds:6900', host='node', user='test', name='owned',
        path='/mnt/owned', port=12000, remote_identity={'fs_id': '12'})


def work(action='fs.delete'):
    return {'action': action, 'machine_id': 'machine', 'machine_address': '192.0.2.1',
        'target_user': 'test', 'mds_addr': 'mds:6900', 'parameters': {'fs_name': 'owned'}, 'record': None}


ROUTES = [{'source_host': 'node', 'address': '192.0.2.1', 'machine_id': 'machine', 'user': 'test'}]


def test_filesystem_cleanup_requires_exact_name_cluster_route_user():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row(), work()
    assert matches_cleanup_step(resource, step, ROUTES)
    for key, value in [('machine_id', 'other'), ('target_user', 'root'), ('mds_addr', 'other:6900'),
                        ('parameters', {'fs_name': 'prefix-owned'})]:
        assert not matches_cleanup_step(resource, {**step, key: value}, ROUTES)


def test_saved_mount_cleanup_requires_exact_mount_and_filesystem():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row('mount'), work('mount.unmount')
    step['record'] = {'mount_path': '/mnt/owned', 'fs_name': 'owned'}
    assert matches_cleanup_step(resource, step, ROUTES)
    step['record']['mount_path'] = '/mnt/owned/subdir'
    assert not matches_cleanup_step(resource, step, ROUTES)


def test_cache_cleanup_never_uses_group_or_member_prefix():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row('cache'), work('cache.stop')
    step['record'] = {'member_id': 'owned', 'listen_port': 12000}
    assert matches_cleanup_step(resource, step, ROUTES)
    step['record']['member_id'] = 'owned-extra'
    assert not matches_cleanup_step(resource, step, ROUTES)


def test_cache_delete_binds_separate_frozen_control_route():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row('cache'), work('cache.delete')
    step.update(machine_id='control', machine_address='192.0.2.2', parameters={'member_id': 'owned'})
    binding = {'machine_id': 'control', 'control_connection': ['192.0.2.2', 22, 'test']}
    assert matches_cleanup_step(resource, step, ROUTES, binding=binding)
    assert not matches_cleanup_step(resource, {**step, 'machine_address': '192.0.2.99'}, ROUTES, binding=binding)
    assert not matches_cleanup_step(resource, step, [], binding=binding)


def test_privileged_saved_mount_binds_original_owner_process_and_namespace():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row('mount'), work('mount.unmount')
    resource.remote_identity = {'id': 12, 'target': '/mnt/owned', 'source': 'DingoFS:owned', 'fstype': 'fuse.dingofs',
        'process': {'pid': 123, 'start_time': '456', 'exe': '/opt/dingo-client'}}
    step.update(target_user='root', record={'origin': 'external', 'client_user': 'test', 'mount_path': '/mnt/owned',
        'fs_name': 'owned', 'identity': {'mount_id': '12', 'pid': 123, 'start_ticks': '456',
                                       'exe': '/opt/dingo-client', 'namespace': 'mnt:[123]'}})
    assert matches_cleanup_step(resource, step, ROUTES, namespace='mnt:[123]')
    assert not matches_cleanup_step(resource, step, ROUTES, namespace='mnt:[999]')
    step['record']['client_user'] = 'another'
    assert not matches_cleanup_step(resource, step, ROUTES, namespace='mnt:[123]')


def test_privileged_external_cache_stop_is_narrow_member_adapter():
    from dingofs_platform.functional.retention_cleanup import matches_cleanup_step
    resource, step = row('cache'), work('cache.stop_external')
    resource.remote_identity = {'member_id': 'owned', 'group_name': 'group', 'ip': '192.0.2.1', 'port': 12000}
    step.update(target_user='root', parameters={'member_id': 'owned'}, record={'member_id': 'owned',
                'group_name': 'group', 'listen_ip': '192.0.2.1', 'listen_port': 12000})
    assert matches_cleanup_step(resource, step, ROUTES)
    step['action'] = 'cache.stop'
    assert not matches_cleanup_step(resource, step, ROUTES)
    step = work('cache.delete')
    step['parameters'] = {'member_id': 'owned'}
    binding = {'machine_id': 'machine', 'control_connection': ['192.0.2.1', 22, 'test']}
    assert matches_cleanup_step(resource, step, ROUTES, binding=binding)
    step['action'] = 'cache.delete_batch'
    assert not matches_cleanup_step(resource, step, ROUTES)
