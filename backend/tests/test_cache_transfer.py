import threading
import time
from types import SimpleNamespace
import paramiko
import pytest
from dingofs_platform.resources import cache_transfer

CONFIG = SimpleNamespace(host="test", port=22, username="test", password="unused")
ARTIFACT = {"path": "/cache/dingo-cache", "sha256": "a" * 64}


def test_stuck_sftp_handshake_is_closed_by_deadline(monkeypatch):
    stopped = threading.Event()
    class Client:
        def set_missing_host_key_policy(self, policy): pass
        def connect(self, **kwargs): pass
        def get_transport(self): return self
        def open_session(self, **kwargs):
            stopped.wait(2)
            raise paramiko.SSHException("closed")
        def open_sftp(self):
            stopped.wait(2)
            raise paramiko.SSHException("closed")
        def close(self): stopped.set()
    monkeypatch.setattr(cache_transfer.paramiko, "SSHClient", Client)
    started = time.monotonic()
    with pytest.raises(ValueError, match="超时"):
        with cache_transfer.upload_binary(CONFIG, ARTIFACT, lambda: False, started + 0.1):
            pass
    assert stopped.is_set()
    assert time.monotonic() - started < 1.5


def test_disconnect_during_cleanup_does_not_mask_success(monkeypatch):
    closed = []
    class Channel:
        def settimeout(self, seconds): pass
        def invoke_subsystem(self, subsystem): pass
    class SFTP:
        def get_channel(self): return Channel()
        def mkdir(self, *args, **kwargs): pass
        def chmod(self, *args): pass
        def put(self, *args, **kwargs): pass
        def remove(self, path): raise paramiko.SSHException("connection lost")
        def rmdir(self, path): pass
        def close(self): raise EOFError("closed")
    class Client:
        def set_missing_host_key_policy(self, policy): pass
        def connect(self, **kwargs): pass
        def get_transport(self): return self
        def open_session(self, **kwargs): return Channel()
        def open_sftp(self): return SFTP()
        def close(self): closed.append(True)
    monkeypatch.setattr(cache_transfer.paramiko, "SSHClient", Client)
    monkeypatch.setattr(cache_transfer.paramiko, "SFTPClient", lambda channel: SFTP())
    with cache_transfer.upload_binary(CONFIG, ARTIFACT, lambda: False, time.monotonic() + 10) as uploaded:
        assert uploaded["sha256"] == "a" * 64
    assert closed
