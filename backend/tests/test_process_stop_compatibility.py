"""No real process is signalled by these compatibility tests."""
import errno
import signal
import pytest
from dingofs_platform.resources import remote_helper as h

P = dict(pid=98765, start_ticks="100", exe="/opt/dingo-cache", argv=["dingo-cache", "--id=member"])

@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.delattr(h.os, "pidfd_open", raising=False)
    calls = []
    monkeypatch.setattr(h.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(h.time, "sleep", lambda _: None)
    return calls

def identities(monkeypatch, values):
    stream = iter(values)
    monkeypatch.setattr(h, "process_identity", lambda _: next(stream))

def test_old_python_stops_verified_process_and_waits(monkeypatch, legacy):
    identities(monkeypatch, [P, P, P, None])
    assert h.stop_recorded_process(P) is True
    assert legacy == [(P["pid"], signal.SIGTERM)]

def test_legacy_rechecks_identity_immediately_before_signal(monkeypatch, legacy):
    identities(monkeypatch, [P, {**P, "start_ticks": "200"}])
    with pytest.raises(ValueError, match="identity changed"):
        h.stop_recorded_process(P)
    assert legacy == []

def test_process_exits_before_signal(monkeypatch, legacy):
    identities(monkeypatch, [P, None])
    assert h.stop_recorded_process(P) is False
    assert legacy == []

def test_pid_reuse_after_signal_is_not_signalled_again(monkeypatch, legacy):
    identities(monkeypatch, [P, P, {**P, "start_ticks": "200"}])
    assert h.stop_recorded_process(P) is True
    assert len(legacy) == 1

def test_live_process_timeout_is_failure(monkeypatch, legacy):
    monkeypatch.setattr(h, "process_identity", lambda _: P)
    with pytest.raises(ValueError, match="SIGTERM"):
        h.stop_recorded_process(P, timeout=0)
    assert legacy == [(P["pid"], signal.SIGTERM)]

def test_old_kernel_falls_back(monkeypatch, legacy):
    def unavailable(_): raise OSError(errno.ENOSYS, "unsupported")
    monkeypatch.setattr(h.os, "pidfd_open", unavailable, raising=False)
    monkeypatch.setattr(h.signal, "pidfd_send_signal", lambda *_: None, raising=False)
    identities(monkeypatch, [P, P, None])
    assert h.stop_recorded_process(P) is True
    assert len(legacy) == 1

def test_pidfd_permission_errors_are_not_hidden(monkeypatch, legacy):
    def denied(_): raise PermissionError(errno.EPERM, "denied")
    monkeypatch.setattr(h.os, "pidfd_open", denied, raising=False)
    monkeypatch.setattr(h.signal, "pidfd_send_signal", lambda *_: None, raising=False)
    identities(monkeypatch, [P])
    with pytest.raises(PermissionError): h.stop_recorded_process(P)
    assert legacy == []

def test_force_stop_sends_sigkill_and_records_matching_command(monkeypatch, legacy):
    identities(monkeypatch, [P, P, None])
    monkeypatch.setattr(h, 'TRACE_ENABLED', True)
    h.COMMAND_TRACE.clear()
    assert h.stop_recorded_process(P, force=True) is True
    assert legacy == [(P['pid'], signal.SIGKILL)]
    assert h.COMMAND_TRACE[-1]['command'] == 'kill -9 -- 98765'

def test_pidfd_force_stop_sends_sigkill(monkeypatch):
    identities(monkeypatch, [P, P])
    calls=[]
    monkeypatch.setattr(h.os,'pidfd_open',lambda pid:999,raising=False)
    monkeypatch.setattr(h.signal,'pidfd_send_signal',lambda fd,sig:calls.append((fd,sig)),raising=False)
    monkeypatch.setattr(h.os,'close',lambda fd:None)
    monkeypatch.setattr(h.select,'select',lambda *args:([999],[],[]))
    assert h.stop_recorded_process(P,force=True)
    assert calls==[(999,signal.SIGKILL)]
