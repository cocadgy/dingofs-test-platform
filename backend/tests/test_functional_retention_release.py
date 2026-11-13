"""Explicit retention release never fabricates cleanup or loses other owners' locks."""
from copy import deepcopy
import pytest
from sqlalchemy import select
from test_functional_preflight import ready, deny_real_ssh
from test_functional_retention_service import retained
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun, FunctionalResource
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.operations.leases import acquire_leases, LeaseRequest


def setup_run(admin, app, ready, monkeypatch, mode='ok', run_info=None):
    run_id, keys = run_info or retained(admin, app, ready)
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        observation = deepcopy(child.remote_identity['remote_state'])
        observation.update(state='exited', journal_verified=True)
        child.remote_identity = {**child.remote_identity, 'remote_state': observation}
    class Transport:
        def __init__(self, config): pass
        def poll_child(self, payload, cursor, cancel=False):
            assert not cancel and payload['child_id'] == observation['process']['child_id']
            assert 'current' not in payload['immutable_path'].split('/')
            result = deepcopy(observation)
            if mode == 'transport': raise OSError('offline')
            if mode == 'identity': result['process']['pid'] = 999
            if mode == 'journal': result['journal_verified'] = False
            if mode == 'more': result['has_more'] = True
            return result
        def call(self, code):
            return {'ended': mode != 'alive'}
    app.state.functional_transport = Transport
    return run_id, keys


def post(admin, run_id, action='release-retained', confirmed=True):
    return admin.post(f'/api/v1/functional/runs/{run_id}/resources/{action}', json={'confirmed': confirmed})


def test_release_preserves_resources_and_repeat_never_releases_new_owner(admin, app, ready, monkeypatch):
    run_id, keys = setup_run(admin, app, ready, monkeypatch)
    reply = post(admin, run_id)
    assert reply.status_code == 200, reply.text
    assert reply.json()['released'] and reply.json()['retained_count'] == 2
    with app.state.session_factory.begin() as db:
        assert db.get(FunctionalRun, run_id).state == 'needs_attention'
        assert {r.phase for r in db.scalars(select(FunctionalResource))} == {'retained'}
        assert all(r.released_at for r in db.scalars(select(OperationLease)))
        acquire_leases(db, 'resource:new', [LeaseRequest(key) for key in keys])
    assert post(admin, run_id).status_code == 200
    assert post(admin, run_id, 'reacquire-retained').status_code == 409
    with app.state.session_factory() as db:
        assert all(r.released_at is None for r in db.scalars(select(OperationLease).where(OperationLease.owner == 'resource:new')))


@pytest.mark.parametrize('mode', ['transport', 'identity', 'journal', 'more', 'alive', 'active', 'recovery', 'confirmation', 'member', 'cleanup'])
def test_release_refuses_unverified_or_unauthorized(admin, app, ready, monkeypatch, mode):
    run_id, keys = setup_run(admin, app, ready, monkeypatch, mode)
    if mode == 'cleanup':
        monkeypatch.setattr('dingofs_platform.functional.retention_release.cleanup_in_progress', lambda *args: True)
    with app.state.session_factory.begin() as db:
        child = db.scalar(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id))
        if mode == 'active': child.state = 'running'
        if mode == 'recovery': child.result = {**child.result, 'recovery_status': 'failed'}
    if mode == 'member':
        response = admin.post('/api/v1/auth/login', json={'username': 'member', 'password': 'test-password-123'})
        admin.headers['X-CSRF-Token'] = response.json()['csrf_token']
    reply = post(admin, run_id, confirmed=mode != 'confirmation')
    assert reply.status_code in (403, 409, 422), reply.text
    with app.state.session_factory() as db:
        assert all(r.released_at is None for r in db.scalars(select(OperationLease)))
        assert {r.phase for r in db.scalars(select(FunctionalResource))} == {'retained'}


from test_functional_cleanup_api import runner, target
from test_functional_cleanup_service import live
from test_resource_api import begin


def test_old_cleanup_conflicts_with_new_run_then_reacquires_and_verifies(admin, app, ready, monkeypatch, runner):
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    setup_run(admin, app, ready, monkeypatch, run_info=(run_id, keys))
    live(monkeypatch)
    assert post(admin, run_id).status_code == 200
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'functional:new-running', [LeaseRequest(k) for k in keys])
    assert begin(admin, cluster, 'fs.delete', params).status_code == 409
    assert not runner
    # Model the new owner's verified completion in this isolated test database.
    from datetime import datetime, timezone
    with app.state.session_factory.begin() as db:
        for row in db.scalars(select(OperationLease).where(OperationLease.owner == 'functional:new-running')):
            row.released_at = datetime.now(timezone.utc)
    assert post(admin, run_id, 'reacquire-retained').status_code == 200
    response = begin(admin, cluster, 'fs.delete', params)
    assert response.status_code == 202, response.text
    assert admin.get('/api/v1/resource-operations/' + response.json()['id']).json()['state'] == 'succeeded'
    assert [item['action'] for item in runner] == ['fs.delete']


def test_reacquire_restores_original_union_without_mutating_residuals(admin, app, ready, monkeypatch):
    run_id, keys = setup_run(admin, app, ready, monkeypatch)
    assert post(admin, run_id).status_code == 200
    reply = post(admin, run_id, 'reacquire-retained')
    assert reply.status_code == 200, reply.text
    assert reply.json()['released'] is False
    assert post(admin, run_id, 'reacquire-retained').status_code == 200
    with app.state.session_factory() as db:
        leases = list(db.scalars(select(OperationLease)))
        assert {r.key for r in leases if r.released_at is None} == set(keys)
        assert all(r.depth == 1 for r in leases)
        assert {r.phase for r in db.scalars(select(FunctionalResource))} == {'retained'}


def test_release_serializes_new_owner_acquisition_during_remote_check(admin, app, ready, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from dingofs_platform.auth.models import User
    from dingofs_platform.functional.retention_release import release_retained_run
    run_id, keys = setup_run(admin, app, ready, monkeypatch)
    entered, proceed, contender_started, acquired = Event(), Event(), Event(), Event()
    base = app.state.functional_transport
    class BlockingTransport(base):
        def poll_child(self, *args, **kwargs):
            entered.set()
            assert proceed.wait(10)
            return super().poll_child(*args, **kwargs)
    def release():
        with app.state.session_factory.begin() as db:
            db.info.update(functional_settings=app.state.settings, functional_transport=BlockingTransport)
            actor = db.scalar(select(User).where(User.username == 'admin'))
            return release_retained_run(db, actor, run_id, confirmed=True)
    def acquire():
        with app.state.session_factory.begin() as db:
            contender_started.set()
            result = acquire_leases(db, 'functional:new', [LeaseRequest(k) for k in keys])
            assert result.acquired
        acquired.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(release)
        try:
            assert entered.wait(10)
            second = pool.submit(acquire)
            assert contender_started.wait(10)
            assert not acquired.wait(.2)
        finally:
            proceed.set()
        assert first.result(timeout=10)['released']
        second.result(timeout=10)
    with app.state.session_factory() as db:
        assert all(r.released_at is None for r in db.scalars(select(OperationLease).where(OperationLease.owner == 'functional:new')))


def test_prepared_cleanup_blocks_release_and_stale_dispatch_cannot_use_released_authority(admin, app, ready, monkeypatch, runner):
    from types import SimpleNamespace
    from dingofs_platform.resources import execution
    from dingofs_platform.resources.models import ResourceOperation
    run_id, keys, cluster, params = target(admin, app, ready, 'fs.delete')
    setup_run(admin, app, ready, monkeypatch, run_info=(run_id, keys))
    live(monkeypatch)
    execute = execution.run
    monkeypatch.setattr(execution, 'run', lambda *args, **kwargs: None)
    response = begin(admin, cluster, 'fs.delete', params)
    assert response.status_code == 202
    operation_id = response.json()['id']
    assert post(admin, run_id).status_code == 409
    # Confirm zero-start cancellation, then deliver a stale worker claim after
    # release. Even a worker that gets as far as dispatch must recheck ownership.
    with app.state.session_factory.begin() as db:
        operation = db.get(ResourceOperation, operation_id)
        operation.state, operation.result = 'failed', {'zero_start': True}
    assert post(admin, run_id).status_code == 200
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'functional:new-running', [LeaseRequest(k) for k in keys])
        db.get(ResourceOperation, operation_id).state = 'pending'
    execute(SimpleNamespace(app=app, state=SimpleNamespace()), operation_id)
    value = admin.get('/api/v1/resource-operations/' + operation_id).json()
    assert value['state'] == 'failed' and value['error_code'] == 'cleanup_not_verified'
    assert not runner
