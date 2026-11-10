"""Existing confirmed resource operations use exact server-only cleanup bindings."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_functional_preflight import ready, deny_real_ssh
from test_functional_cleanup_service import setup, live
from test_resource_api import begin
from dingofs_platform.auth.models import User
from dingofs_platform.functional.models import FunctionalResource
from dingofs_platform.inventory.models import Cluster
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.resources.models import ManagedResource, ResourceOperation


@pytest.fixture
def runner(app):
    """Keep real preparation and command building; fake only SSH execution."""
    import json
    import shlex
    from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
    calls = []
    def transport(config, cmd, **kwargs):
        argv = shlex.split(cmd.resource_script)
        assert argv[:2] == ['python3', '-c']
        request = json.loads(argv[3])
        request['command_user'] = cmd.target_user
        calls.append(request)
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user, cmd.expected_home or '/home/' + cmd.target_user, '/opt/dingo'),
            json.dumps({'state': 'succeeded', 'returncode': 0, 'data': {}}), '', 0)
    app.state.resource_transport = transport
    return calls


def target(admin, app, ready, action):
    run_id, keys = setup(admin, app, ready)
    params = {'fs_name': 'owned-fs'}
    with app.state.session_factory.begin() as db:
        cluster = db.get(Cluster, ready[0].cluster_id)
        c = {'id': cluster.id, 'revision': cluster.revision}
        actor = db.scalar(select(User).where(User.username == 'admin'))
        row = db.scalar(select(FunctionalResource).where(FunctionalResource.resource_id == 'resource-0'))
        if action == 'mount.unmount':
            row.kind, row.path = 'mount', '/mnt/owned'
            row.remote_identity = {'id': 123, 'target': '/mnt/owned', 'source': 'DingoFS:owned-fs',
                'fstype': 'fuse.dingofs', 'process': {'pid': 12, 'start_time': '34', 'exe': '/opt/dingo-client',
                    'fs_name': 'owned-fs', 'mds_addr': 'node1.test:6900', 'mount_path': '/mnt/owned'}}
            saved = ManagedResource(creator_id=actor.id, cluster_id=cluster.id, kind='mount', name='/mnt/owned', state='mounted',
                data={'machine_id': ready[3]['id'], 'target_user': 'test', 'mount_path': '/mnt/owned', 'fs_name': 'owned-fs',
                      'state_dir': '/tmp/managed/owned', 'log_dir': '/tmp/managed/owned/logs'})
            db.add(saved)
            db.flush()
            params = {'resource_id': saved.id}
        elif action.startswith('cache.'):
            row.kind, row.name, row.port = 'cache', 'owned-member', 12000
            row.remote_identity = {'member_id': 'owned-member', 'group_name': 'owned-group', 'ip': '192.0.2.1',
                                  'port': 12000, 'process': {'pid': 12, 'start': '34', 'exe': '/opt/dingo-cache', 'member_id': 'owned-member'}}
            saved = ManagedResource(creator_id=actor.id, cluster_id=cluster.id, kind='cache', name='owned-group', state='running',
                data={'members': [{'machine_id': ready[3]['id'], 'target_user': 'test',
                    'member_id': 'owned-member', 'listen_port': 12000,
                    'state_dir': '/tmp/managed/member', 'log_dir': '/tmp/managed/member/logs'}]})
            db.add(saved)
            db.flush()
            params = {'resource_id': saved.id} if action == 'cache.stop' else {'member_id': 'owned-member'}
    return run_id, keys, c, params


@pytest.mark.parametrize('action', ['fs.delete', 'mount.unmount', 'cache.stop', 'cache.delete'])
def test_exact_cleanup_executes_without_releasing_parent_leases(admin, app, ready, runner, monkeypatch, action):
    run_id, keys, cluster, params = target(admin, app, ready, action)
    live(monkeypatch)
    if action == 'cache.delete':
        from dingofs_platform.functional import retention
        with app.state.session_factory() as db:
            saved_id = db.scalar(select(ManagedResource.id).where(ManagedResource.kind == 'cache'))
        stopped = begin(admin, cluster, 'cache.stop', {'resource_id': saved_id})
        assert stopped.status_code == 202, stopped.text
        monkeypatch.setattr(retention, 'probe_resource', lambda db, actor, parent, child, row:
            {**retention.resource_request(row), 'status': 'present', 'identity': {**row.remote_identity, 'process': None}})
    response = begin(admin, cluster, action, params)
    assert response.status_code == 202, response.text
    value = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert value['state'] == 'succeeded', value
    assert '_functional_cleanup' not in value['payload']
    assert [item['action'] for item in runner] == (['cache.stop', action] if action == 'cache.delete' else [action])
    with app.state.session_factory() as db:
        assert set(db.scalars(select(OperationLease.key).where(OperationLease.owner == 'functional:' + run_id,
                   OperationLease.released_at.is_(None)))) == set(keys)
        context = db.get(ResourceOperation, value['id']).parameters['_functional_cleanup']
        assert context['run_id'] == run_id and context['resource_id'] == 'resource-0'
        if action in ('mount.unmount', 'cache.stop'):
            assert db.get(ManagedResource, params['resource_id']).state == ('unmounted' if action == 'mount.unmount' else 'stopped')


def test_cleanup_revalidates_identity_before_worker_dispatch(admin, app, ready, runner, monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.functional import retention
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    execute = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    response = begin(admin, cluster, 'fs.delete', params)
    assert response.status_code == 202, response.text
    monkeypatch.setattr(retention, 'probe_resource', lambda db, actor, parent, child, row:
        {**retention.resource_request(row), 'status': 'present', 'identity': {'fs_id': 'different'}})
    execute(SimpleNamespace(app=app, state=SimpleNamespace()), response.json()['id'])
    value = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert value['state'] == 'failed' and value['error_code'] == 'cleanup_not_verified'
    assert not runner


@pytest.mark.parametrize('changed', [None, 'namespace', 'owner'])
def test_saved_external_mount_uses_only_bound_root_adapter(admin, app, ready, runner, monkeypatch, changed):
    from dingofs_platform.functional import retention
    run_id, keys, cluster, params = target(admin, app, ready, 'mount.unmount')
    with app.state.session_factory.begin() as db:
        saved = db.get(ManagedResource, params['resource_id'])
        saved.data = {**saved.data, 'origin': 'external', 'target_user': 'root', 'client_user': 'test',
            'identity': {'mount_id': '123', 'pid': 12, 'start_ticks': '34', 'exe': '/opt/dingo-client', 'namespace': 'mnt:[123]'}}
        if changed == 'owner':
            saved.data = {**saved.data, 'client_user': 'another'}
    def probe(db, actor, parent, child, row):
        return {**retention.resource_request(row), 'status': 'present', 'identity': row.remote_identity,
                'namespace': 'mnt:[999]' if changed == 'namespace' else 'mnt:[123]',
                'process_namespace': 'mnt:[123]', 'boot_id': 'boot-123'}
    monkeypatch.setattr(retention, 'probe_resource', probe)
    response = begin(admin, cluster, 'mount.unmount', params)
    assert response.status_code == (409 if changed else 202), response.text
    if not changed:
        value = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
        assert value['state'] == 'succeeded', value
        assert runner[0]['action'] == 'mount.unmount' and runner[0]['command_user'] == 'root'
        assert runner[0]['record']['client_user'] == 'test'
    else:
        assert not runner


def test_external_cache_stop_binds_single_member_and_readonly_control_phase(admin, app, ready, runner, monkeypatch):
    run_id, keys, cluster, params = target(admin, app, ready, 'cache.stop')
    live(monkeypatch)
    with app.state.session_factory.begin() as db:
        saved = db.get(ManagedResource, params['resource_id'])
        saved.data = {'origin': 'external', 'members': [{**saved.data['members'][0], 'origin': 'external'}]}
        # A real prior read-only list operation supplies the trusted discovered registration.
        actor = db.scalar(select(User).where(User.username == 'admin'))
        from dingofs_platform.auth.models import Session
        session = db.scalar(select(Session).where(Session.user_id == actor.id))
        from dingofs_platform.resources.views import now
        from datetime import timedelta
        db.add(ResourceOperation(actor_id=actor.id, session_id=session.id, cluster_id=cluster['id'],
            cluster_revision=cluster['revision'], action='cache.list', request_id='prior-list', request_digest='prior-list',
            parameters={}, steps=[], state='succeeded', lease_token='readonly-list-token', expires_at=now() + timedelta(minutes=10),
            result={'steps': [{'data': {'result': {'members': [{'member_id': 'owned-member', 'group_name': 'owned-group',
                'ip': '192.0.2.1', 'port': 12000}]}}}]}))
    response = begin(admin, cluster, 'cache.stop', {'member_ids': ['owned-member']})
    assert response.status_code == 202, response.text
    value = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert value['state'] == 'succeeded', value
    assert [(r['action'], r['command_user']) for r in runner] == [('cache.verify_members', 'test'), ('cache.stop_external', 'root')]


def test_readonly_release_blocks_newer_retry_but_not_known_ended_old_failure(admin, app, ready, monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.functional import retention
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    response = begin(admin, cluster, 'fs.delete', params)
    assert response.status_code == 202, response.text
    path = '/api/v1/functional/runs/' + run_id + '/resources/verify'
    assert admin.post(path).json()['code'] == 'retention_cleanup_active'
    with app.state.session_factory.begin() as db:
        previous = db.get(ResourceOperation, response.json()['id'])
        previous.state, previous.result = 'failed', {'steps': [{'remote_ended': True}]}
        retry = ResourceOperation(actor_id=previous.actor_id, session_id=previous.session_id, cluster_id=previous.cluster_id,
            cluster_revision=previous.cluster_revision, action=previous.action, request_id='retry', request_digest='retry',
            parameters={'retry_operation_id': previous.id}, steps=previous.steps, state='pending', lease_token='retry-token',
            expires_at=previous.expires_at, result={})
        db.add(retry)
        db.flush()
        retry_id = retry.id
    assert admin.post(path).json()['code'] == 'retention_cleanup_active'
    with app.state.session_factory.begin() as db:
        db.get(ResourceOperation, retry_id).state = 'succeeded'
    monkeypatch.setattr(retention, 'probe_resource', lambda db, actor, parent, child, row:
        {**retention.resource_request(row), 'status': 'absent', 'identity': None})
    verified = admin.post(path)
    assert verified.status_code == 200 and verified.json()['remaining_resources'] == [], verified.text


def test_batch_mount_schema_never_uses_single_resource_cleanup_exception(admin, app, ready, runner, monkeypatch):
    _, _, cluster, params = target(admin, app, ready, 'mount.unmount')
    live(monkeypatch)
    response = begin(admin, cluster, 'mount.unmount', {'resource_ids': [params['resource_id']]})
    assert response.status_code == 409, response.text
    assert not runner


@pytest.mark.parametrize('changed', [None, 'namespace', 'boot_id'])
def test_saved_unmount_freezes_live_scope_and_only_matching_scope_can_release(admin, app, ready, runner, monkeypatch, changed):
    from dingofs_platform.functional import retention
    run_id, keys, cluster, params = target(admin, app, ready, 'mount.unmount')
    live(monkeypatch)
    response = begin(admin, cluster, 'mount.unmount', params)
    assert response.status_code == 202, response.text
    with app.state.session_factory() as db:
        context = db.get(ResourceOperation, response.json()['id']).parameters['_functional_cleanup']
        assert context['mount_scope'] == {'namespace': 'mnt:[123]', 'boot_id': 'boot-123'}
    def absent(db, actor, parent, child, row):
        return {**retention.resource_request(row), 'status': 'absent', 'identity': None,
                'namespace': 'mnt:[other]' if changed == 'namespace' else 'mnt:[123]',
                'boot_id': 'another-boot' if changed == 'boot_id' else 'boot-123'}
    monkeypatch.setattr(retention, 'probe_resource', absent)
    verified = admin.post('/api/v1/functional/runs/' + run_id + '/resources/verify')
    assert verified.status_code == 200, verified.text
    assert bool(verified.json()['remaining_resources']) is bool(changed)


@pytest.mark.parametrize('prior_state,result,want', [
    ('pending', {}, 409), ('running', {}, 409), ('interrupted', {}, 409),
    ('failed', {}, 409), ('failed', {'zero_start': True}, 202),
])
def test_distinct_requests_cannot_bypass_durable_exact_object_cleanup_guard(admin, app, ready, monkeypatch, prior_state, result, want):
    from dingofs_platform.resources import execution
    _, _, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'fs.delete', params)
    assert first.status_code == 202, first.text
    with app.state.session_factory.begin() as db:
        previous = db.get(ResourceOperation, first.json()['id'])
        previous.state, previous.result = prior_state, result
    second = begin(admin, cluster, 'fs.delete', params)
    assert second.status_code == want, second.text
    if want == 409:
        assert second.json()['code'] == 'operation_conflict'


def clone_operation(db, previous, *, parameters=None, state='interrupted'):
    from copy import deepcopy
    retry = ResourceOperation(actor_id=previous.actor_id, session_id=previous.session_id,
        cluster_id=previous.cluster_id, cluster_revision=previous.cluster_revision, action=previous.action,
        request_id='distinct-operation', request_digest='distinct-operation',
        parameters=deepcopy(previous.parameters) if parameters is None else parameters,
        steps=deepcopy(previous.steps), state=state, lease_token='distinct-token', expires_at=previous.expires_at,
        result={})
    db.add(retry)
    db.flush()
    return retry


def test_unknown_retry_descendant_blocks_new_exact_object_admission(admin, app, ready, monkeypatch):
    from dingofs_platform.resources import execution
    _, _, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'fs.delete', params)
    assert first.status_code == 202, first.text
    with app.state.session_factory.begin() as db:
        previous = db.get(ResourceOperation, first.json()['id'])
        previous.state, previous.result = 'failed', {'zero_start': True}
        clone_operation(db, previous, parameters={'retry_operation_id': previous.id})
    second = begin(admin, cluster, 'fs.delete', params)
    assert second.status_code == 409 and second.json()['code'] == 'operation_conflict', second.text


def test_dispatch_rechecks_other_unknown_exact_cleanup_without_releasing_any_owner(admin, app, ready, runner, monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    execute = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'fs.delete', params)
    assert first.status_code == 202, first.text
    with app.state.session_factory.begin() as db:
        previous = db.get(ResourceOperation, first.json()['id'])
        clone_operation(db, previous)
        acquire_leases(db, 'resource:unrelated-owner', [LeaseRequest('machine:unrelated')])
    execute(SimpleNamespace(app=app, state=SimpleNamespace()), first.json()['id'])
    value = admin.get('/api/v1/resource-operations/' + first.json()['id']).json()
    assert value['state'] == 'failed' and value['error_code'] == 'cleanup_not_verified', value
    assert not runner
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))


def test_worker_prelocks_full_functional_owner_union_before_every_inventory_lock(admin, app, ready, runner, monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.operations import leases
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    execute = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'fs.delete', params)
    assert first.status_code == 202, first.text
    full_keys = {*keys, 'machine:another-original-target'}
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'functional:' + run_id, [leases.LeaseRequest('machine:another-original-target')])
    lock_keys, inventory = leases.lock_keys, execution.lock_inventory
    events = []
    def keys_before_business(db, requests):
        if full_keys <= {request.key for request in requests}:
            db.info['full_owner_prelocked'] = True
            events.append('full-owner')
        return lock_keys(db, requests)
    def inventory_after_union(db):
        assert db.info.get('full_owner_prelocked'), 'inventory locked before full functional-owner lease union'
        events.append('inventory')
        return inventory(db)
    monkeypatch.setattr(leases, 'lock_keys', keys_before_business)
    monkeypatch.setattr(execution, 'lock_keys', keys_before_business)
    monkeypatch.setattr(execution, 'lock_inventory', inventory_after_union)
    execute(SimpleNamespace(app=app, state=SimpleNamespace()), first.json()['id'])
    assert events.count('inventory') >= 3
    assert runner and admin.get('/api/v1/resource-operations/' + first.json()['id']).json()['state'] == 'succeeded'


def test_saved_mount_scope_is_rechecked_before_dispatch(admin, app, ready, runner, monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.functional import retention
    _, _, cluster, params = target(admin, app, ready, 'mount.unmount')
    live(monkeypatch)
    execute = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'mount.unmount', params)
    assert first.status_code == 202, first.text
    monkeypatch.setattr(retention, 'probe_resource', lambda db, actor, parent, child, row:
        {**retention.resource_request(row), 'status': 'present', 'identity': row.remote_identity,
         'namespace': 'mnt:[changed]', 'process_namespace': 'mnt:[changed]', 'boot_id': 'boot-123'})
    execute(SimpleNamespace(app=app, state=SimpleNamespace()), first.json()['id'])
    value = admin.get('/api/v1/resource-operations/' + first.json()['id']).json()
    assert value['state'] == 'failed' and value['error_code'] == 'cleanup_not_verified'
    assert not runner


def test_concurrent_distinct_requests_dispatch_only_one_exact_cleanup(admin, app, ready, runner, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _, _, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    transport = app.state.resource_transport
    started, finish = Event(), Event()
    def held_transport(*args, **kwargs):
        started.set()
        assert finish.wait(timeout=10), 'bounded fake transport was not released'
        return transport(*args, **kwargs)
    app.state.resource_transport = held_transport
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(begin, admin, cluster, 'fs.delete', params)
        try:
            assert started.wait(timeout=10), 'first cleanup did not reach fake transport'
            second = begin(admin, cluster, 'fs.delete', params)
            assert second.status_code == 409 and second.json()['code'] == 'operation_conflict', second.text
        finally:
            finish.set()
        response = first.result(timeout=10)
    assert response.status_code == 202 and len(runner) == 1, response.text


@pytest.mark.parametrize('entrypoint', ['authenticate', 'cancel', 'get'])
def test_cleanup_operation_entrypoints_lock_account_then_full_owner_before_inventory(admin, app, ready, monkeypatch, entrypoint):
    from dingofs_platform.auth import users
    from dingofs_platform.resources import execution, routes
    from dingofs_platform.operations import leases
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    live(monkeypatch)
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    first = begin(admin, cluster, 'fs.delete', params)
    assert first.status_code == 202, first.text
    full_keys = {*keys, 'machine:another-original-target'}
    with app.state.session_factory.begin() as db:
        leases.acquire_leases(db, 'functional:' + run_id, [leases.LeaseRequest('machine:another-original-target')])
        if entrypoint == 'authenticate':
            operation = db.get(ResourceOperation, first.json()['id'])
            operation.state, operation.lease_token = 'needs_password', 'test-challenge' * 3
            operation.challenge_digest = execution.digest('test-challenge' * 3)
    accounts, lock_keys, inventory = users.lock_accounts, leases.lock_keys, execution.lock_inventory
    events = []
    def accounts_first(db):
        db.info['cleanup_accounts_prelocked'] = True
        return accounts(db)
    def full_owner_next(db, requests):
        if full_keys <= {request.key for request in requests}:
            assert db.info.get('cleanup_accounts_prelocked'), 'owner union locked before account'
            db.info['cleanup_full_owner_prelocked'] = True
        return lock_keys(db, requests)
    def inventory_last(db):
        assert db.info.get('cleanup_full_owner_prelocked'), 'entrypoint inventory before full functional owner'
        events.append('inventory')
        return inventory(db)
    monkeypatch.setattr(users, 'lock_accounts', accounts_first)
    monkeypatch.setattr(leases, 'lock_keys', full_owner_next)
    monkeypatch.setattr(execution, 'lock_inventory', inventory_last)
    monkeypatch.setattr(routes, 'lock_inventory', inventory_last)
    path = '/api/v1/resource-operations/' + first.json()['id']
    if entrypoint == 'authenticate':
        response = admin.post(path + '/authenticate', json={'challenge': 'test-challenge' * 3, 'password': 'sudo-test'})
    elif entrypoint == 'cancel':
        response = admin.post(path + '/cancel')
    else:
        response = admin.get(path)
    assert response.status_code == 200 and events, response.text
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))


def test_reported_cleanup_runs_actual_probe_and_adapter_before_readonly_release(admin, app, ready, monkeypatch):
    """Only external I/O is fake: production probe source and command adapter execute."""
    import contextlib
    import io
    import json
    import shlex
    import subprocess
    from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    present, calls = [True], []
    def query(argv, **kwargs):
        assert argv == ['/opt/dingo', 'fs', 'list', '--mdsaddr', 'node1.test:6900', '--format', 'json']
        calls.append('probe')
        rows = [{'fs_name': 'owned-fs', 'fs_id': 77}] if present[0] else []
        return SimpleNamespace(returncode=0, stdout=json.dumps({'result': {'fs_infos': rows}}), stderr='')
    def probe_transport(config, code):
        assert config.host == '192.0.2.1' and config.username == 'test'
        stdout = io.StringIO()
        with monkeypatch.context() as patch, contextlib.redirect_stdout(stdout):
            patch.setattr(subprocess, 'run', query)
            exec(compile(code, '<actual-retention-probe>', 'exec'), {})
        return json.loads(stdout.getvalue())
    def adapter_transport(config, command, **kwargs):
        args = shlex.split(command.resource_script)
        assert args[:2] == ['python3', '-c']
        namespace = {'__name__': 'isolated_actual_cleanup_adapter'}
        exec(compile(args[2], '<actual-resource-adapter>', 'exec'), namespace)
        def run_command(argv, **kwargs):
            assert argv == ['dingo', 'fs', 'delete', 'owned-fs', '--mdsaddr', 'node1.test:6900', '--noconfirm', '--format', 'json']
            calls.append('delete')
            present[0] = False
            return {'result': {}}
        namespace['run_command'] = run_command
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = namespace['main'](json.loads(args[3]))
        return ClusterCommandResult(ExecutionIdentity(command.target_user, command.expected_home or '/home/test', '/opt/dingo'),
                                    stdout.getvalue(), '', code)
    app.state.functional_retention_transport = probe_transport
    app.state.resource_transport = adapter_transport
    response = begin(admin, cluster, 'fs.delete', params)
    assert response.status_code == 202, response.text
    value = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert value['state'] == 'succeeded', value
    assert calls[-1] == 'delete' and calls.count('probe') >= 3
    with app.state.session_factory() as db:
        assert all(row.released_at is None for row in db.scalars(select(OperationLease)))
    verified = admin.post('/api/v1/functional/runs/' + run_id + '/resources/verify')
    assert verified.status_code == 200, verified.text
    assert verified.json()['remaining_resources'] == []
    with app.state.session_factory() as db:
        assert all(row.released_at is not None for row in db.scalars(select(OperationLease)))
