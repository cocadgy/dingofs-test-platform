from unittest.mock import MagicMock

import paramiko
import pytest
from cryptography.fernet import Fernet
from dingofs_platform.inventory.ssh_transport import SSHConfig, run_session
from dingofs_platform.inventory.host_trust import key_info


def test_ssh_automatically_trusts_without_loading_saved_keys():
    client = MagicMock()
    config = SSHConfig('node', 22, 'login', 'secret', '/missing', key_info(paramiko.RSAKey.generate(1024)))
    assert run_session(config, {}, 2, 1024, client_factory=lambda: client) == {}
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.AutoAddPolicy)
    client.load_host_keys.assert_not_called()
    client.get_host_keys.assert_not_called()
    client.connect.assert_called_once()


@pytest.mark.parametrize('failure', [False, True])
def test_create_automatically_collects_and_preserves_machine(admin, app, monkeypatch, failure):
    from dingofs_platform.inventory import hardware_routes
    calls = []
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    def collect(config, **kwargs):
        calls.append(config.host)
        if failure:
            raise RuntimeError('secret must not leak')
        return {'status': 'success', 'hardware_info': {'cpu': {'logical_cores': 8}}}
    monkeypatch.setattr(hardware_routes, 'collect', collect)
    response = admin.post('/api/v1/machines', json={
        'name': '自动采集', 'address': '192.0.2.1', 'ssh_user': 'root', 'ssh_password': 'secret',
    })
    assert response.status_code == 201, response.text
    assert response.json()['collection_status'] == 'collecting'
    assert calls == ['192.0.2.1']
    row = admin.get('/api/v1/machines/' + response.json()['id']).json()
    assert row['collection_status'] == ('failed' if failure else 'success')
    if not failure:
        assert row['hardware_info']['cpu']['logical_cores'] == 8
    assert 'secret' not in str(row)


def test_create_without_password_is_saved_with_collection_reason(admin):
    response = admin.post('/api/v1/machines', json={
        'name': '尚未配置密码', 'address': '192.0.2.2', 'ssh_user': 'root',
    })
    assert response.status_code == 201
    assert response.json()['collection_status'] == 'failed'
    assert 'SSH 密码' in response.json()['collection_error']


def test_old_pending_challenge_is_no_longer_shown(admin):
    from dingofs_platform.inventory.models import Machine
    response = admin.post('/api/v1/machines', json={
        'name': '旧待确认机器', 'address': '192.0.2.3', 'ssh_user': 'root',
    })
    id = response.json()['id']
    with admin.app.state.session_factory.begin() as db:
        row = db.get(Machine, id)
        row.collection_status = 'needs_trust'
        row.collection_error = 'SSH 主机尚未受信任'
        row.ssh_trust_pending = {'expired': True}
    row = admin.get('/api/v1/machines/' + id).json()
    assert row['ssh_host_trust']['pending'] is None
    assert row['collection_status'] == 'failed'
    assert '自动信任' in row['collection_error']
