from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dingofs_platform.tool_packages.routes import JobInput
from dingofs_platform.tool_packages.service import expire


def test_unlimited_request_is_explicit_and_strict():
    assert JobInput(action='auto_install', tool='dtt', no_timeout=True).no_timeout is True
    assert JobInput(action='auto_install', tool='dtt').no_timeout is False
    with pytest.raises(ValidationError):
        JobInput(action='auto_install', tool='dtt', no_timeout='false')
    with pytest.raises(ValidationError):
        JobInput(action='check', no_timeout=True)


def test_unlimited_install_does_not_expire_on_poll():
    row = SimpleNamespace(state='running', action='auto_install', options={'no_timeout': True},
                          deadline=datetime.now(timezone.utc)-timedelta(days=2), log='')
    expire(None, row)
    assert row.state == 'running'


def test_unlimited_ssh_session_has_no_timer(monkeypatch):
    from dingofs_platform.tool_packages import ssh_session
    from unittest.mock import MagicMock
    client = MagicMock()
    monkeypatch.setattr(ssh_session.paramiko, 'SSHClient', lambda: client)
    def forbidden_timer(*args):
        pytest.fail('Unlimited session must not create a deadline timer')
    monkeypatch.setattr(ssh_session.threading, 'Timer', forbidden_timer)
    remote = ssh_session.Remote(SimpleNamespace(host='host', port=22, username='test', password='secret'),
                                None, lambda **kw: None, 'test')
    assert remote.remaining() == float('inf')
    import socket
    sock = client.get_transport().sock
    sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, 'TCP_USER_TIMEOUT'):
        sock.setsockopt.assert_any_call(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 60000)
    remote.close()


def test_unlimited_api_passes_no_deadline_to_installer(admin):
    from test_performance_api import setup
    from dingofs_platform.tool_packages.models import ToolSource
    mid = setup(admin)['machine_id']
    with admin.app.state.session_factory.begin() as db:
        db.add(ToolSource(id='default', machine_id=mid, directory='/tmp/tools', image='image:test', allow_cached=False))
    def install(target, source, options, timeout, report):
        assert timeout is None
        assert options['no_timeout'] is True
        return {'items': []}
    admin.app.state.tool_automatic_transport = install
    response = admin.post('/api/v1/machines/'+mid+'/tool-jobs',
                          json={'action':'auto_install', 'tool':'dtt', 'no_timeout':True})
    assert response.status_code == 202, response.text
    job = admin.get('/api/v1/machines/'+mid+'/tool-jobs').json()[0]
    assert job['state'] == 'success', job
    assert job['deadline'] is None


@pytest.mark.parametrize('responsive', [True, False])
def test_connection_probe_requires_ssh_reply(monkeypatch, responsive):
    from dingofs_platform.tool_packages import ssh_session
    class Transport:
        active = True
        def is_active(self):return self.active
        def global_request(self, name, wait):
            assert wait is True
    transport = Transport()
    class Client:
        def get_transport(self):return transport
        def close(self):transport.active = False
    class Watchdog:
        def __init__(self, seconds, callback):
            assert seconds == 30
            self.callback = callback
        def start(self):
            if not responsive:self.callback()
        def cancel(self):pass
    monkeypatch.setattr(ssh_session.threading, 'Timer', Watchdog)
    remote = object.__new__(ssh_session.Remote)
    remote.client = Client()
    if responsive:
        remote.check_connection()
        assert transport.active
    else:
        with pytest.raises(ConnectionError):remote.check_connection()
