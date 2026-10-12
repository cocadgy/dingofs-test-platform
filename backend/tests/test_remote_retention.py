"""Completed remote results stay bounded independently of concurrent jobs."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.remote import manager as remote
from dingofs_platform.remote.models import RemoteSession


@pytest.fixture
def supervisor(monkeypatch):
    engine = create_engine("sqlite://")
    RemoteSession.__table__.create(engine)
    AuditEvent.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(remote, "time", SimpleNamespace(monotonic=lambda: clock.value))
    # SQLite returns naive timestamps; this fixture never touches a network DB.
    monkeypatch.setattr(remote, "now", datetime.now)
    manager = remote.RemoteManager(
        SimpleNamespace(state=SimpleNamespace(session_factory=sessions))
    )
    yield manager, sessions, clock
    for slot in manager.slots.values():
        manager._cleanup(slot)
    engine.dispose()


def add_session(supervisor, sid, kind="read"):
    manager, sessions, _ = supervisor
    with sessions.begin() as db:
        db.add(
            RemoteSession(
                id=sid,
                actor_id="actor",
                login_session_id="login",
                kind=kind,
                cluster_id="cluster",
                machine_id="machine",
                cluster_revision=1,
                machine_revision=1,
                target_user="test",
                parameters={},
                state="running",
                expires_at=remote.now() + timedelta(hours=1),
            )
        )
    slot = remote.Slot()
    manager.slots[sid] = slot
    return slot


def done(manager, sid, kind="read"):
    manager._event(sid, manager.slots[sid], {"type": "done"}, kind)


def sweep_once(manager):
    waits = iter((False, True))
    manager.stop_event = SimpleNamespace(wait=lambda _: next(waits))
    manager._sweep()


def test_success_retains_full_ttl_after_slow_completion(supervisor):
    manager, sessions, clock = supervisor
    slot = add_session(supervisor, "read")
    clock.value = 700.0
    manager._event("read", slot, {"type": "text", "text": "kept result"}, "read")
    done(manager, "read")

    clock.value = 1001.0  # Old launch-based retention has elapsed.
    sweep_once(manager)
    assert manager.slots.get("read") is slot
    assert slot.result == {"text": "kept result"}
    with sessions() as db:
        row = db.get(RemoteSession, "read")
        assert row.state == "succeeded"
        assert (row.expires_at - row.closed_at).total_seconds() == pytest.approx(
            900, abs=1
        )

    clock.value = 1601.0
    sweep_once(manager)
    assert "read" not in manager.slots


def test_slot_limit_evicts_oldest_completion_and_clears_listing(
    supervisor, monkeypatch
):
    manager, sessions, clock = supervisor
    monkeypatch.setattr(remote, "MAX_RETAINED_SLOTS", 1, raising=False)
    add_session(supervisor, "created-first")
    listing = add_session(supervisor, "completed-first", "files")
    manager._event(
        "completed-first",
        listing,
        {"type": "files", "files": [{"name": "old.INFO", "size": 1}]},
        "files",
    )
    done(manager, "completed-first", "files")
    clock.value += 1
    done(manager, "created-first")

    assert "completed-first" not in manager.slots
    assert "created-first" in manager.slots
    with sessions() as db:
        row = db.get(RemoteSession, "completed-first")
        assert row.state == "closed"
        assert row.error_code == "result_evicted"
        assert row.result is None


def test_byte_limit_counts_spools_and_read_results_and_removes_files(
    supervisor, monkeypatch
):
    manager, sessions, clock = supervisor
    monkeypatch.setattr(remote, "MAX_RETAINED_BYTES", 80, raising=False)
    spool = add_session(supervisor, "download", "download")
    manager._event(
        "download", spool, {"type": "download_start", "size": 40}, "download"
    )
    manager._event(
        "download", spool, {"type": "download_chunk", "data": b"x" * 40}, "download"
    )
    path = Path(spool.tempdir.name)
    done(manager, "download", "download")
    clock.value += 1
    result = add_session(supervisor, "read")
    manager._event("read", result, {"type": "text", "text": "x" * 50}, "read")
    done(manager, "read")

    assert not path.exists()
    assert spool.tempdir is None
    assert "download" not in manager.slots
    assert manager.slots["read"].result == {"text": "x" * 50}
    with sessions() as db:
        assert db.get(RemoteSession, "download").error_code == "result_evicted"


def test_cache_pressure_preserves_active_worker_and_bounds_failed_slots(
    supervisor, monkeypatch
):
    manager, sessions, clock = supervisor
    monkeypatch.setattr(remote, "MAX_RETAINED_SLOTS", 1, raising=False)
    active = add_session(supervisor, "active", "terminal")
    active.job = object()
    for sid in ("failure-1", "failure-2", "failure-3"):
        add_session(supervisor, sid)
        manager.finish(sid, "failed", "connection_failed")
        clock.value += 1

    assert set(manager.slots) == {"active", "failure-3"}
    assert not active.stopped
    with sessions() as db:
        assert db.get(RemoteSession, "active").state == "running"
        assert db.get(RemoteSession, "failure-1").error_code == "connection_failed"


def test_cache_does_not_remove_slot_before_worker_cleanup(supervisor, monkeypatch):
    manager, _, clock = supervisor
    monkeypatch.setattr(remote, "MAX_RETAINED_SLOTS", 1, raising=False)
    finishing = add_session(supervisor, "finishing")
    finishing.job = object()
    done(manager, "finishing")
    clock.value += 1
    add_session(supervisor, "newest")
    done(manager, "newest")
    assert manager.slots["finishing"] is finishing
    assert not finishing.stopped


def test_attached_stream_keeps_final_output_until_socket_releases_it(
    supervisor, monkeypatch
):
    manager, _, clock = supervisor
    monkeypatch.setattr(remote, "MAX_RETAINED_SLOTS", 1)
    stream = add_session(supervisor, "stream", "terminal")
    assert manager.attach("stream")
    manager.enqueue("stream", {"type": "text", "text": "last terminal output"})
    done(manager, "stream", "terminal")
    clock.value += 1
    add_session(supervisor, "read")
    done(manager, "read")

    assert manager.pop("stream") == {"type": "text", "text": "last terminal output"}
    assert manager.pop("stream")["type"] == "closed"
    assert "read" not in manager.slots
    manager.close("stream", "stream_disconnected")
    add_session(supervisor, "later")
    done(manager, "later")
    assert "stream" not in manager.slots
    assert "later" in manager.slots
    assert not stream.attached


def test_evicted_download_reports_unavailable_through_http(admin, monkeypatch):
    from test_remote_security import DownloadJob
    from test_remote_sessions import fixture, start, wait

    _, cluster = fixture(admin)
    admin.app.state.remote_job_factory = DownloadJob
    monkeypatch.setattr(remote, "MAX_RETAINED_BYTES", 250000)
    listing = start(admin, cluster, "files", service_id="svc1")
    listing = wait(admin, listing.json()["id"], {"succeeded"})
    file_id = listing["result"]["files"][0]["file_id"]
    first = start(admin, cluster, "download", service_id="svc1", file_id=file_id)
    first_id = first.json()["id"]
    wait(admin, first_id, {"succeeded"})
    second = start(admin, cluster, "download", service_id="svc1", file_id=file_id)
    second_id = second.json()["id"]
    wait(admin, second_id, {"succeeded"})

    result = wait(admin, first_id, {"closed"})
    assert result["error_code"] == "result_evicted"
    assert result["message"]
    assert result["result"] is None
    unavailable = admin.get(f"/api/v1/remote-sessions/{first_id}/download")
    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "result_evicted"
    assert admin.get(
        f"/api/v1/remote-sessions/{second_id}/download"
    ).content == b"x" * (3 * 65536)


def test_early_worker_failures_are_also_bounded(supervisor, monkeypatch):
    from dingofs_platform.inventory.models import Machine

    manager, sessions, clock = supervisor
    Machine.__table__.create(sessions.kw["bind"])
    with sessions.begin() as db:
        db.add(
            Machine(id="machine", name="node", address="node.invalid", ssh_user="test")
        )
    monkeypatch.setattr(remote, "valid", lambda db, row: True)
    monkeypatch.setattr(remote, "MAX_RETAINED_SLOTS", 1)
    for sid in ("missing-1", "missing-2"):
        slot = add_session(supervisor, sid)
        manager._run(sid, slot, None, None)
        clock.value += 1

    assert set(manager.slots) == {"missing-2"}
    with sessions() as db:
        assert db.get(RemoteSession, "missing-1").error_code == "ssh_password_missing"


def open_download_response(admin, sid):
    from starlette.requests import Request
    from dingofs_platform.remote.routes import download

    request = Request(
        {
            "type": "http",
            "app": admin.app,
            "headers": [
                (b"cookie", ("session=" + admin.cookies.get("session")).encode())
            ],
        }
    )
    return download(sid, request)


def ready_download(admin, cluster, file_id, expected="succeeded"):
    from test_remote_sessions import start, wait

    response = start(admin, cluster, "download", service_id="svc1", file_id=file_id)
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    result = wait(admin, sid, {expected})
    if expected == "closed":
        assert result["error_code"] == "result_evicted"
    return sid


def refreshed_download(admin, cluster):
    from test_remote_sessions import start, wait

    response = start(admin, cluster, "files", service_id="svc1")
    listing = wait(admin, response.json()["id"], {"succeeded"})
    return ready_download(admin, cluster, listing["result"]["files"][0]["file_id"])


def download_pressure_setup(admin, monkeypatch):
    from test_remote_security import DownloadJob
    from test_remote_sessions import fixture, start, wait

    _, cluster = fixture(admin)
    admin.app.state.remote_job_factory = DownloadJob
    monkeypatch.setattr(remote, "MAX_RETAINED_BYTES", 250000)
    listing = start(admin, cluster, "files", service_id="svc1")
    listing = wait(admin, listing.json()["id"], {"succeeded"})
    file_id = listing["result"]["files"][0]["file_id"]
    sid = ready_download(admin, cluster, file_id)
    return cluster, file_id, sid


def test_http_download_survives_cache_pressure_until_transfer_finishes(
    admin, monkeypatch
):
    import asyncio
    from test_remote_sessions import wait

    cluster, file_id, first_id = download_pressure_setup(admin, monkeypatch)
    streaming = open_download_response(admin, first_id)

    async def consume_under_pressure():
        body = await anext(streaming.body_iterator)
        ready_download(admin, cluster, file_id, expected="closed")
        await asyncio.sleep(2.1)  # Exercise the next authorization check.
        async for chunk in streaming.body_iterator:
            body += chunk
        assert body == b"x" * (3 * 65536)

    asyncio.run(consume_under_pressure())
    refreshed_download(admin, cluster)
    result = wait(admin, first_id, {"closed"})
    assert result["error_code"] == "result_evicted"
    assert first_id not in admin.app.state.remote_manager.slots


@pytest.mark.parametrize("interruption", ["disconnect", "cancel"])
def test_http_disconnect_before_first_chunk_releases_download_pin(
    admin, monkeypatch, interruption
):
    import asyncio
    from starlette.requests import ClientDisconnect
    from test_remote_sessions import wait

    cluster, file_id, first_id = download_pressure_setup(admin, monkeypatch)
    streaming = open_download_response(admin, first_id)
    slot = admin.app.state.remote_manager.slots[first_id]
    path = Path(slot.tempdir.name)
    ready_download(admin, cluster, file_id, expected="closed")
    assert path.exists()

    async def disconnected_send(message):
        if interruption == "cancel":
            raise asyncio.CancelledError()
        raise OSError("client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    exception = asyncio.CancelledError if interruption == "cancel" else ClientDisconnect
    with pytest.raises(exception):
        asyncio.run(
            streaming(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                disconnected_send,
            )
        )
    refreshed_download(admin, cluster)
    result = wait(admin, first_id, {"closed"})
    assert result["error_code"] == "result_evicted"
    assert not path.exists()
