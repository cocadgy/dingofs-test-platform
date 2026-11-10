"""Owner-wide lease release uses live exact-resource evidence and persisted end proof."""
import ast
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_rerun_service import original
from dingofs_platform.auth.models import User
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalResource
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.operations.leases import acquire_leases, LeaseRequest


def retained(admin, app, ready):
    run_id = original(admin, app, ready)
    with app.state.session_factory.begin() as db:
        parent = db.get(FunctionalRun, run_id)
        parent.state = 'needs_attention'
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child.state = 'needs_attention'
        child.launch_attempted_at = datetime.now(timezone.utc)
        process = dict(state='exited', child_id=child.id, launch_token='token', pid=12, start_time='123')
        child.remote_identity = {'launch_token': 'token', 'remote_state': {'process': process, 'returncode': 1,
            'end_proof': {**{k: v for k, v in process.items() if k != 'state'}, 'returncode': 1}}}
        child.result = {**child.result, 'cleanup_status': 'retained'}
        for index in range(2):
            db.add(FunctionalResource(child_id=child.id, resource_id=f'resource-{index}', kind='directory',
                cluster='node1.test:6900', host='node1.test', user='test', path=f'/tmp/owned/{index}',
                owned=True, phase='retained', remote_identity={'device_inode': f'1:{index + 2}'}))
        keys = ['cluster:' + parent.cluster_id, 'machine:' + parent.machine_id, 'runtime:' + parent.machine_id]
        acquire_leases(db, 'functional:' + run_id, [LeaseRequest(key) for key in keys])
    return run_id, keys


def verify(app, run_id, statuses):
    from dingofs_platform.functional.retention import verify_retained_resources
    def transport(config, code):
        request = ast.literal_eval(code.splitlines()[0].removeprefix('REQUEST='))
        assert config.username == 'test'
        result = {key: request[key] for key in ('child_id', 'resource_id', 'kind', 'expected_identity', 'target')}
        status = statuses[request['resource_id']]
        return {**result, 'status': status, 'identity': request['expected_identity'] if status == 'present' else None}
    with app.state.session_factory.begin() as db:
        db.info['functional_settings'] = app.state.settings
        db.info['functional_retention_transport'] = transport
        actor = db.scalar(select(User).where(User.username == 'admin'))
        return verify_retained_resources(db, actor, run_id)


def test_one_remaining_resource_keeps_every_owner_lease(admin, app, ready):
    run_id, keys = retained(admin, app, ready)
    evidence = verify(app, run_id, {'resource-0': 'absent', 'resource-1': 'present'})
    assert evidence.remaining_resources == frozenset(keys)
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))
    evidence = verify(app, run_id, {'resource-0': 'absent', 'resource-1': 'absent'})
    assert evidence.verified_resources == frozenset(keys) and not evidence.remaining_resources
    with app.state.session_factory() as db:
        assert all(row.released_at is not None for row in db.scalars(select(OperationLease)))
        assert {row.phase for row in db.scalars(select(FunctionalResource))} == {'removed'}


def test_failed_recovery_never_releases_even_after_resources_absent(admin, app, ready):
    run_id, keys = retained(admin, app, ready)
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        child.result = {**child.result, 'recovery_status': 'failed'}
    evidence = verify(app, run_id, {'resource-0': 'absent', 'resource-1': 'absent'})
    assert not evidence.recovery_ok
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))


def test_cache_probe_queries_frozen_control_then_original_member_host(admin, app, ready):
    import copy
    from conftest import machine
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.functional.retention import probe_resource
    run_id, _ = retained(admin, app, ready)
    member = machine(admin, 'member')
    calls = []
    def transport(config, code):
        calls.append(config.host)
        request = ast.literal_eval(code.splitlines()[0].removeprefix('REQUEST='))
        if len(calls) == 1:
            assert config.host == '192.0.2.1' and 'cache_registration(REQUEST)' in code
            return {'members': [{'member_id': 'cache-one', 'group_name': 'group', 'ip': '192.0.2.2', 'port': 12000}]}
        assert config.host == '192.0.2.2'
        assert request['registration']['members'][0]['member_id'] == 'cache-one'
        return {'status': 'present'}
    with app.state.session_factory.begin() as db:
        db.info.update(functional_settings=app.state.settings, functional_retention_transport=transport)
        actor = db.scalar(select(User).where(User.username == 'admin'))
        parent = db.get(FunctionalRun, run_id)
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        row = db.scalar(select(FunctionalResource).where(FunctionalResource.resource_id == 'resource-0'))
        m = db.get(Machine, member['id'])
        m.address, m.aliases = '192.0.2.2', ['member.test']
        m.ssh_password_ciphertext = db.get(Machine, parent.machine_id).ssh_password_ciphertext
        snapshot = copy.deepcopy(parent.snapshot)
        snapshot['runtime_binding']['resolved_targets'].append({'source_host': 'member.test', 'address': m.address,
            'machine_id': m.id, 'port': m.ssh_port, 'user': m.ssh_user})
        from types import SimpleNamespace
        parent = SimpleNamespace(snapshot=snapshot)
        row.kind, row.name, row.host, row.port = 'cache', 'cache-one', 'member.test', 12000
        assert probe_resource(db, actor, parent, child, row)['status'] == 'present'
    assert calls == ['192.0.2.1', '192.0.2.2']


def test_orphan_mount_absent_in_current_namespace_without_history_keeps_all_leases(admin, app, ready):
    run_id, keys = retained(admin, app, ready)
    with app.state.session_factory.begin() as db:
        row = db.scalar(select(FunctionalResource).where(FunctionalResource.resource_id == 'resource-0'))
        row.kind, row.name, row.path = 'mount', 'owned-fs', '/mnt/owned'
        row.remote_identity = {'id': 123, 'target': '/mnt/owned', 'source': 'DingoFS:owned-fs',
            'fstype': 'fuse.dingofs', 'process': {'pid': 12, 'start_time': '34', 'exe': '/opt/dingo-client',
                'fs_name': 'owned-fs', 'mds_addr': 'node1.test:6900', 'mount_path': '/mnt/owned'}}
        acquire_leases(db, 'resource:unrelated-owner', [LeaseRequest('machine:unrelated')])
    # The original process may have ended while its orphan mount lives elsewhere.
    evidence = verify(app, run_id, {'resource-0': 'absent', 'resource-1': 'absent'})
    assert evidence.remaining_resources == frozenset(keys)
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))
        assert db.scalar(select(FunctionalResource).where(FunctionalResource.resource_id == 'resource-0')).phase == 'unknown'
