"""Lifecycle regressions for supervisor output and explicit access revocation."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.remote.access import now
from dingofs_platform.remote.manager import RemoteManager, Slot
from dingofs_platform.remote.models import RemoteSession
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from test_remote_sessions import FakeJob, fixture, start, wait


def test_terminal_normal_exit_delivers_queued_text_before_closed():
    # Local SQLite only: exercise the real terminal state transition and queue.
    engine = create_engine("sqlite://")
    RemoteSession.__table__.create(engine)
    AuditEvent.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    manager = RemoteManager(
        SimpleNamespace(state=SimpleNamespace(session_factory=sessions))
    )
    with sessions.begin() as db:
        row = RemoteSession(
            actor_id="actor",
            login_session_id="login",
            kind="terminal",
            cluster_id="cluster",
            machine_id="machine",
            cluster_revision=1,
            machine_revision=1,
            target_user="root",
            parameters={},
            state="running",
            expires_at=now() + timedelta(hours=1),
        )
        db.add(row)
        db.flush()
        sid = row.id
    manager.slots[sid] = Slot()
    manager.enqueue(sid, {"type": "text", "text": "last command output\r\n"})
    manager._event(sid, manager.slots[sid], {"type": "done"}, "terminal")
    assert manager.pop(sid) == {"type": "text", "text": "last command output\r\n"}
    assert manager.pop(sid)["type"] == "closed"
    engine.dispose()


def test_admin_can_close_session_created_by_another_login(admin, app):
    machine, cluster = fixture(admin)
    response = start(
        admin, cluster, "terminal", machine_id=machine["id"], confirmed=True
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    wait(admin, sid, {"ready"})
    second = TestClient(app)
    login = second.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password-123"},
    )
    second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    response = second.delete("/api/v1/remote-sessions/" + sid)
    assert response.status_code == 204, response.text
    assert wait(admin, sid, {"closed"})["state"] == "closed"
    second.close()


class DownloadJob(FakeJob):
    def __init__(self, config, request, **kwargs):
        super().__init__(config, request, **kwargs)
        if request.kind == "download":
            body = b"x" * (3 * 65536)
            self.events.put(
                {"type": "download_start", "name": request.name, "size": len(body)}
            )
            for offset in range(0, len(body), 65536):
                self.events.put(
                    {"type": "download_chunk", "data": body[offset : offset + 65536]}
                )
            self.events.put({"type": "done"})


def test_delete_revokes_download_that_already_opened_the_spool(admin, app):
    from dingofs_platform.remote.routes import download

    _, cluster = fixture(admin)
    app.state.remote_job_factory = DownloadJob
    listing = start(admin, cluster, "files", service_id="svc1")
    listing = wait(admin, listing.json()["id"], {"succeeded"})
    response = start(
        admin,
        cluster,
        "download",
        service_id="svc1",
        file_id=listing["result"]["files"][0]["file_id"],
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    wait(admin, sid, {"succeeded"})
    request = Request(
        {
            "type": "http",
            "app": app,
            "headers": [
                (b"cookie", ("session=" + admin.cookies.get("session")).encode())
            ],
        }
    )
    streaming = download(sid, request)

    async def consume_then_cancel():
        assert await anext(streaming.body_iterator) == b"x" * 65536
        app.state.remote_manager.close(sid)
        # The streaming generator promises periodic authorization checks.
        await asyncio.sleep(2.1)
        with pytest.raises(StopAsyncIteration):
            await anext(streaming.body_iterator)

    asyncio.run(consume_then_cancel())


def login_client(app, username="member"):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "test-password-123"},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def member_resources(admin, app):
    from dingofs_platform.auth.models import User
    from dingofs_platform.inventory.models import Cluster, Machine
    from sqlalchemy import select

    machine, cluster = fixture(admin)
    with app.state.session_factory.begin() as db:
        member = db.scalar(select(User).where(User.username == "member"))
        member_id, member_revision = member.id, member.revision
        db.get(Machine, machine["id"]).creator_id = member_id
        db.get(Cluster, cluster["id"]).creator_id = member_id
    return machine, cluster, member_id, member_revision


def start_follow(client, cluster):
    response = start(client, cluster, "files", service_id="svc1")
    assert response.status_code == 202, response.text
    listing = wait(client, response.json()["id"], {"succeeded"})
    response = start(
        client,
        cluster,
        "log-follow",
        service_id="svc1",
        file_id=listing["result"]["files"][0]["file_id"],
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    wait(client, sid, {"ready"})
    return sid


def test_member_reads_owned_cluster_and_machine_but_not_other_machine(admin, app):
    from conftest import machine
    from dingofs_platform.inventory.models import Cluster

    _, cluster, _, _ = member_resources(admin, app)
    other = machine(admin, "other-owner")
    with app.state.session_factory.begin() as db:
        row = db.get(Cluster, cluster["id"])
        row.status_snapshot = {
            "services": [
                *row.status_snapshot["services"],
                {
                    "id": "svc2",
                    "host": other["address"],
                    "role": "mds",
                    "log_dir": "/var/log/dingo",
                },
            ]
        }
    member = login_client(app)
    try:
        response = start(member, cluster, "files", service_id="svc1")
        assert response.status_code == 202, response.text
        listing = wait(member, response.json()["id"], {"succeeded"})
        response = start(
            member,
            cluster,
            "read",
            service_id="svc1",
            file_id=listing["result"]["files"][0]["file_id"],
        )
        assert response.status_code == 202, response.text
        assert (
            wait(member, response.json()["id"], {"succeeded"})["result"]["text"]
            == "private log <script>"
        )
        assert start(member, cluster, "files", service_id="svc2").status_code == 403
        assert (
            start(
                member, cluster, "terminal", machine_id=other["id"], confirmed=True
            ).status_code
            == 403
        )
    finally:
        member.close()


def test_websocket_requires_origin_cookie_and_single_attachment(admin, app):
    from starlette.websockets import WebSocketDisconnect

    machine, cluster = fixture(admin)
    response = start(
        admin, cluster, "terminal", machine_id=machine["id"], confirmed=True
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    wait(admin, sid, {"ready"})
    url = "/api/v1/remote-sessions/" + sid + "/stream"
    with (
        pytest.raises(WebSocketDisconnect) as rejected,
        admin.websocket_connect(url),
    ):
        pass
    assert rejected.value.code == 1008
    anonymous = TestClient(app)
    try:
        with (
            pytest.raises(WebSocketDisconnect) as rejected,
            anonymous.websocket_connect(url, headers={"Origin": "http://testserver"}),
        ):
            pass
        assert rejected.value.code == 1008
    finally:
        anonymous.close()
    with admin.websocket_connect(url, headers={"Origin": "http://testserver"}):
        with (
            pytest.raises(WebSocketDisconnect) as rejected,
            admin.websocket_connect(url, headers={"Origin": "http://testserver"}),
        ):
            pass
        assert rejected.value.code == 1008
    wait(admin, sid, {"closed"})


def test_log_follow_rejects_terminal_input_without_forwarding(admin):
    from starlette.websockets import WebSocketDisconnect

    _, cluster = fixture(admin)
    sid = start_follow(admin, cluster)
    job = FakeJob.instances[-1]
    with admin.websocket_connect(
        "/api/v1/remote-sessions/" + sid + "/stream",
        headers={"Origin": "http://testserver"},
    ) as ws:
        ws.send_json({"type": "input", "data": "touch /tmp/not-authorized\r"})
        with pytest.raises(WebSocketDisconnect) as rejected:
            ws.receive_json()
        assert rejected.value.code == 1008
    wait(admin, sid, {"closed"})
    assert job.sent == []
    assert job.closed


@pytest.mark.parametrize("reason", ["logout", "disable", "log_directory"])
def test_live_follow_revoked_by_login_account_or_directory_change(admin, app, reason):
    from dingofs_platform.inventory.models import Cluster
    from starlette.websockets import WebSocketDisconnect

    _, cluster, member_id, member_revision = member_resources(admin, app)
    member = login_client(app)
    try:
        sid = start_follow(member, cluster)
        job = FakeJob.instances[-1]
        with member.websocket_connect(
            "/api/v1/remote-sessions/" + sid + "/stream",
            headers={"Origin": "http://testserver"},
        ) as ws:
            if reason == "logout":
                response = member.post("/api/v1/auth/logout")
                assert response.status_code == 204, response.text
            elif reason == "disable":
                response = admin.patch(
                    "/api/v1/users/" + member_id,
                    json={"base_revision": member_revision, "disabled": True},
                )
                assert response.status_code == 200, response.text
            else:
                with app.state.session_factory.begin() as db:
                    row = db.get(Cluster, cluster["id"])
                    row.status_snapshot = {
                        "services": [
                            {
                                **row.status_snapshot["services"][0],
                                "log_dir": "/var/log/replaced",
                            }
                        ]
                    }
            try:
                event = ws.receive_json()
                assert event["type"] == "closed"
            except WebSocketDisconnect as exc:
                assert exc.code in (1000, 1008)
        with app.state.session_factory() as db:
            assert db.get(RemoteSession, sid).state == "closed"
        assert job.closed
    finally:
        member.close()


@pytest.mark.parametrize("root", ["/", "/var/..", "/var/log/../..", "//", "//var/.."])
def test_normalized_filesystem_root_is_not_a_log_directory(admin, app, root):
    from dingofs_platform.inventory.models import Cluster

    _, cluster = fixture(admin)
    with app.state.session_factory.begin() as db:
        row = db.get(Cluster, cluster["id"])
        row.status_snapshot = {
            "services": [{**row.status_snapshot["services"][0], "log_dir": root}]
        }
    response = start(admin, cluster, "files", service_id="svc1")
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_log_directory"


class ChallengeJob(FakeJob):
    def __init__(self, config, request, **kwargs):
        super().__init__(config, request, **kwargs)
        if request.kind == "read":
            while not self.events.empty():
                self.events.get_nowait()
            if kwargs.get("password") == " temporary-remote-secret ":
                self.events.put({"type": "text", "text": "authenticated log"})
                self.events.put({"type": "done"})
            else:
                self.events.put({"type": "auth", "account": request.target_user})


def test_auth_challenge_is_single_use_and_password_is_not_persisted(admin, app):
    import json

    from sqlalchemy import select

    _, cluster = fixture(admin)
    app.state.remote_job_factory = ChallengeJob
    response = start(admin, cluster, "files", service_id="svc1")
    listing = wait(admin, response.json()["id"], {"succeeded"})
    response = start(
        admin,
        cluster,
        "read",
        service_id="svc1",
        file_id=listing["result"]["files"][0]["file_id"],
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    challenge = wait(admin, sid, {"needs_password"})["challenge"]
    password = " temporary-remote-secret "
    endpoint = "/api/v1/remote-sessions/" + sid + "/authenticate"
    response = admin.post(
        endpoint,
        json={"challenge": "invalid-challenge-token-012345", "password": password},
    )
    assert response.status_code == 409, response.text
    with app.state.session_factory() as db:
        assert db.get(RemoteSession, sid).auth_attempts == 0
    response = admin.post(endpoint, json={"challenge": challenge, "password": password})
    assert response.status_code == 202, response.text
    result = wait(admin, sid, {"succeeded"})
    assert result["result"]["text"] == "authenticated log"
    assert (
        admin.post(
            endpoint, json={"challenge": challenge, "password": password}
        ).status_code
        == 409
    )
    with app.state.session_factory() as db:
        row = db.get(RemoteSession, sid)
        persisted = {col.name: getattr(row, col.name) for col in row.__table__.columns}
        assert password not in str(persisted)
        assert row.challenge_hash is None
        assert row.auth_attempts == 1
        assert password not in json.dumps(
            [event.detail for event in db.scalars(select(AuditEvent))]
        )


def test_network_websocket_disconnect_reaps_without_asgi_error(admin, app, caplog):
    import json
    import socket
    import threading
    import time
    import uvicorn
    from websockets.sync.client import connect

    machine, cluster = fixture(admin)
    response = start(
        admin, cluster, "terminal", machine_id=machine["id"], confirmed=True
    )
    sid = response.json()["id"]
    wait(admin, sid, {"ready"})
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_config=None))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]))
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        with connect(
            f"ws://127.0.0.1:{port}/api/v1/remote-sessions/{sid}/stream",
            origin=f"http://127.0.0.1:{port}",
            additional_headers={"Cookie": "session=" + admin.cookies.get("session")},
            open_timeout=5,
        ) as ws:
            FakeJob.instances[-1].events.put({"type": "text", "text": "socket smoke"})
            assert json.loads(ws.recv(timeout=5)) == {
                "type": "text",
                "text": "socket smoke",
            }
        wait(admin, sid, {"closed"})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
    assert "Exception in ASGI application" not in caplog.text
