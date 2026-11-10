"""Admission behind a positively identified owner, with real lease transactions."""
import pytest
from sqlalchemy import select
from test_functional_preflight import ready, deny_real_ssh
from test_functional_scheduler import advance, children, held, finished, ingest, scheduler
from dingofs_platform.functional.models import FunctionalRun, FunctionalModuleRun


def submit(admin, ready, key):
    spec = ready[0].model_dump(mode='json')
    check = admin.post('/api/v1/functional/preflight', json=spec)
    assert check.status_code == 200, check.text
    data = check.json()
    assert data['can_start'], data
    response = admin.post('/api/v1/functional/runs', json={**spec, 'version': 2,
        'idempotency_key': key, 'preflight_token': data['token'],
        'confirmed_impacts': data['required_confirmations']})
    assert response.status_code == 202, response.text
    return response.json(), data


def running_owner(admin, app, ready):
    parent, _ = submit(admin, ready, 'owner-a')
    decision = advance(app, parent['id'])
    assert decision.action == 'launch'
    process = finished(decision)['process']
    process['state'] = 'running'
    with app.state.session_factory.begin() as db:
        scheduler().record_observation(db, parent['id'], decision.child_id,
            {'process': process, 'cursor_before': {}})
    assert held(app, parent['id'])
    return parent['id'], decision


def test_running_owner_allows_queue_then_fresh_launch(admin, app, ready, tmp_path):
    owner, decision = running_owner(admin, app, ready)
    ready[2].failed_check = 'mount_identity'  # owner's temporary occupancy
    waiting, checked = submit(admin, ready, 'waiting-b')
    assert any(c['code'] == 'resource_wait' and c['ok'] for c in checked['checks'])
    assert waiting['state'] == 'queued' and '等待' in waiting['phase']
    assert not held(app, waiting['id'])
    assert advance(app, waiting['id']).action == 'wait'
    assert children(app, waiting['id'])[0].launch_attempted_at is None
    outcome = finished(decision)
    outcome['events'][-1]['data']['execution_targets'] = decision.payload['context']['resolved_targets']
    ingest(app, owner, decision, outcome, tmp_path)
    assert advance(app, owner).action == 'done'
    assert not held(app, owner)
    ready[2].failed_check = None
    assert advance(app, waiting['id']).action == 'launch'
    assert held(app, waiting['id'])


@pytest.mark.parametrize('change', ['unknown', 'retained', 'protocol', 'fake_owner', 'permission'])
def test_unsafe_or_unauthorized_contention_is_not_queueable(admin, app, ready, change):
    owner, decision = running_owner(admin, app, ready)
    with app.state.session_factory.begin() as db:
        parent = db.get(FunctionalRun, owner)
        child = db.get(FunctionalModuleRun, decision.child_id)
        if change == 'unknown': parent.state = child.state = 'unknown'
        if change == 'retained': parent.state = child.state = 'needs_attention'
        if change == 'protocol': child.remote_identity = {**child.remote_identity, 'protocol_error': 'invalid'}
        if change == 'fake_owner':
            from dingofs_platform.operations.models import OperationLease
            for lease in db.scalars(select(OperationLease).where(OperationLease.owner == 'functional:' + owner)):
                lease.owner = 'functional:nonexistent'
        if change == 'permission':
            from dingofs_platform.auth.models import User
            actor = db.scalar(select(User).where(User.username == 'admin'))
            actor.role = 'member'
            from dingofs_platform.inventory.models import Machine
            db.get(Machine, ready[3]['id']).creator_id = db.scalar(select(User.id).where(User.username == 'member'))
    result = admin.post('/api/v1/functional/preflight', json=ready[0].model_dump(mode='json'))
    assert result.status_code == 403 or not result.json()['can_start']


@pytest.mark.parametrize('change', ['permission', 'remote'])
def test_queued_request_rechecks_before_dispatch(admin, app, ready, tmp_path, change):
    owner, decision = running_owner(admin, app, ready)
    waiting, _ = submit(admin, ready, 'waiting-b')
    outcome = finished(decision)
    outcome['events'][-1]['data']['execution_targets'] = decision.payload['context']['resolved_targets']
    ingest(app, owner, decision, outcome, tmp_path)
    advance(app, owner)
    if change == 'remote': ready[2].failed_check = 'mount_identity'
    else:
        from dingofs_platform.auth.models import User
        with app.state.session_factory.begin() as db:
            db.scalar(select(User).where(User.username == 'admin')).disabled = True
    assert advance(app, waiting['id']).action == 'done'
    child = children(app, waiting['id'])[0]
    assert child.state == 'failed' and child.launch_attempted_at is None
    assert not held(app, waiting['id'])


@pytest.mark.parametrize('change', ['cancel', 'retained', 'source', 'authentication', 'runtime'])
def test_wait_does_not_bypass_admission_or_dispatch_guards(admin, app, ready, change):
    owner, decision = running_owner(admin, app, ready)
    if change in ('cancel', 'retained'):
        waiting, _ = submit(admin, ready, 'waiting-b')
        if change == 'cancel':
            assert admin.post('/api/v1/functional/runs/' + waiting['id'] + '/stop').status_code == 200
        else:
            with app.state.session_factory.begin() as db:
                db.get(FunctionalRun, owner).state = 'needs_attention'
                db.get(FunctionalModuleRun, decision.child_id).state = 'needs_attention'
        assert advance(app, waiting['id']).action == ('done' if change == 'cancel' else 'wait')
        assert not held(app, waiting['id'])
        assert children(app, waiting['id'])[0].launch_attempted_at is None
        assert held(app, owner)
    else:
        if change == 'source':
            path = ready[1] / 'conf/env/base.yaml'
            path.write_text(path.read_text() + '\n# changed source\n')
        if change == 'runtime': ready[2].runtime['image_id'] = 'sha256:' + 'f' * 64
        if change == 'authentication':
            from dingofs_platform.inventory.credentials import encrypt_password
            from dingofs_platform.inventory.models import Machine
            with app.state.session_factory.begin() as db:
                db.get(Machine, ready[3]['id']).ssh_password_ciphertext = encrypt_password(
                    'revoked-password', app.state.settings.credential_encryption_key)
        response = admin.post('/api/v1/functional/preflight', json=ready[0].model_dump(mode='json'))
        assert response.status_code == 409 or not response.json()['can_start']
