"""Report warming must not consume functional-run monitoring workers."""
from contextlib import contextmanager
import threading
from types import SimpleNamespace

from dingofs_platform.functional.manager import FunctionalManager


def test_prefetch_queue_is_bounded_deduplicated_and_shutdown_does_not_wait(monkeypatch):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    sessions, warmed, active = [], [], set()
    lock = threading.Lock()
    @contextmanager
    def session_factory():
        session = SimpleNamespace(info={})
        with lock:
            sessions.append(session)
        yield session
    app = SimpleNamespace(state=SimpleNamespace(session_factory=session_factory, settings=object()))
    def prefetch(db, run_id, child_id):
        with lock:
            active.add(child_id)
            warmed.append(child_id)
            if len(active) == 2:
                entered.set()
        assert release.wait(5)
        with lock:
            active.remove(child_id)
    monkeypatch.setattr('dingofs_platform.functional.reports.prefetch_report', prefetch)
    manager = FunctionalManager(app)
    try:
        accepted = [manager.queue_report_prefetch('run', str(index)) for index in range(20)]
        assert accepted.count(True) == 8
        assert manager.queue_report_prefetch('run', '0') is False
        assert entered.wait(3)
        assert len(warmed) == 2
        def stop():
            manager.stop()
            stopped.set()
        thread = threading.Thread(target=stop)
        thread.start()
        assert stopped.wait(.5), 'shutdown waited for blocked report SSH'
        assert manager.queue_report_prefetch('run', 'new') is False
    finally:
        release.set()
        manager.stop()
    # Pending work was cancelled; each started worker got its own session.
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert len(warmed) == 2


def test_prefetch_executor_failure_does_not_escape_to_monitor(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError('cannot start a thread')
    monkeypatch.setattr('dingofs_platform.functional.manager.ThreadPoolExecutor', unavailable)
    manager = FunctionalManager(SimpleNamespace(state=SimpleNamespace()))
    try:
        assert manager.queue_report_prefetch('run', 'child') is False
    finally:
        manager.stop()
