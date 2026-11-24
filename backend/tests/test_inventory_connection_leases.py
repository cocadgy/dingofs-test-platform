"""Connection identity edits must preserve live operation lease ownership."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from conftest import machine
from dingofs_platform.operations.leases import LeaseRequest, acquire_leases, release_verified, VerificationEvidence


@pytest.mark.parametrize('key_type,mode', [('machine', 'exclusive'), ('machine', 'shared'),
                                         ('runtime', 'exclusive'), ('runtime', 'shared')])
@pytest.mark.parametrize('field,value', [('address', 'moved.test'), ('ssh_port', 2222), ('ssh_user', 'moved')])
def test_connection_edit_rejected_until_lease_release(admin, app, key_type, mode, field, value):
    node = machine(admin)
    key = key_type + ':' + node['id']
    with app.state.session_factory.begin() as db:
        assert acquire_leases(db, 'tool:held', [LeaseRequest(key, mode)]).acquired
    response = admin.patch('/api/v1/machines/' + node['id'], json={'base_revision': node['revision'], field: value})
    assert response.status_code == 409, response.text
    assert response.json()['code'] == 'operation_conflict'
    current = admin.get('/api/v1/machines/' + node['id']).json()
    assert current[field] == node[field] and current['revision'] == node['revision']
    with app.state.session_factory.begin() as db:
        release_verified(db, 'tool:held', VerificationEvidence('tool:held', True, True,
            frozenset({key}), frozenset(), datetime.now(timezone.utc)))
    response = admin.patch('/api/v1/machines/' + node['id'], json={'base_revision': node['revision'], field: value})
    assert response.status_code == 200, response.text
    assert response.json()[field] == value


def test_metadata_credentials_and_unchanged_connection_allowed_while_leased(admin, app):
    from cryptography.fernet import Fernet
    node = machine(admin)
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    with app.state.session_factory.begin() as db:
        assert acquire_leases(db, 'tool:held', [LeaseRequest('machine:' + node['id']),
                                               LeaseRequest('runtime:' + node['id'])]).acquired
    response = admin.patch('/api/v1/machines/' + node['id'], json={
        'base_revision': node['revision'], 'name': 'renamed', 'tags': ['updated'],
        'ssh_password': 'rotated-secret', **{key: node[key] for key in ('address', 'ssh_port', 'ssh_user')}})
    assert response.status_code == 200, response.text
    assert response.json()['name'] == 'renamed'
    assert response.json()['tags'] == ['updated']
    assert response.json()['has_ssh_password'] is True
    assert 'rotated-secret' not in response.text


def test_connection_edit_waits_for_inflight_lease_admission(admin, app):
    from concurrent.futures import ThreadPoolExecutor
    import time
    node = machine(admin)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with app.state.session_factory.begin() as db:
            assert acquire_leases(db, 'tool:starting', [LeaseRequest('runtime:' + node['id'], 'shared')]).acquired
            response = pool.submit(admin.patch, '/api/v1/machines/' + node['id'],
                json={'base_revision': node['revision'], 'address': 'moved.test'})
            deadline = time.monotonic() + 5
            with app.state.engine.connect() as observer:
                while time.monotonic() < deadline:
                    waiting = observer.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                                                    "AND NOT granted AND database = (SELECT oid FROM pg_database "
                                                    "WHERE datname = current_database())"))
                    observer.rollback()
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting, 'edit did not wait for operation admission transaction'
        result = response.result(timeout=5)
    assert result.status_code == 409, result.text
    assert admin.get('/api/v1/machines/' + node['id']).json()['address'] == node['address']
