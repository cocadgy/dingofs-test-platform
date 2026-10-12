import queue
import time
from conftest import machine, register_cluster
from dingofs_platform.inventory.models import Cluster, Machine


class FakeJob:
    instances = []

    def __init__(self, config, request, **kwargs):
        self.request = request
        self.events = queue.Queue()
        self.alive = True
        self.sent = []
        self.closed = False
        self.__class__.instances.append(self)
        if request.kind == "files":
            self.events.put(
                {
                    "type": "files",
                    "files": [{"name": "mds.INFO", "size": 42, "mtime": 1}],
                    "truncated": False,
                }
            )
            self.events.put({"type": "done"})
        elif request.kind == "read":
            self.events.put(
                {
                    "type": "text",
                    "text": "private log <script>",
                    "cursor": {"device": 1, "inode": 2, "offset": 42},
                }
            )
            self.events.put({"type": "done"})
        else:
            self.events.put({"type": "ready"})

    def poll(self, timeout=0.05):
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, event):
        self.sent.append(event)

    def close(self):
        self.closed = True
        self.alive = False


def fixture(admin):
    m = machine(admin)
    c = register_cluster(admin, m)
    with admin.app.state.session_factory.begin() as db:
        row = db.get(Cluster, c["id"])
        row.status_snapshot = {
            "services": [
                {
                    "id": "svc1",
                    "host": m["address"],
                    "role": "mds",
                    "log_dir": "/var/log/dingo",
                }
            ]
        }
    admin.app.state.remote_job_factory = FakeJob
    return m, c


def wait(client, sid, expected):
    for _ in range(100):
        response = client.get("/api/v1/remote-sessions/" + sid)
        assert response.status_code == 200, response.text
        result = response.json()
        if result["state"] in expected:
            return result
        time.sleep(0.02)
    raise AssertionError(result)


def start(client, cluster, kind, **kw):
    return client.post(
        "/api/v1/remote-sessions",
        json={"cluster_id": cluster["id"], "kind": kind, **kw},
    )


def test_files_read_ids_and_no_log_body_persisted(admin):
    m, c = fixture(admin)
    result = start(admin, c, "files", service_id="svc1")
    assert result.status_code == 202, result.text
    listing = wait(admin, result.json()["id"], {"succeeded"})
    fid = listing["result"]["files"][0]["file_id"]
    read = start(admin, c, "read", service_id="svc1", file_id=fid)
    assert read.status_code == 202, read.text
    result = wait(admin, read.json()["id"], {"succeeded"})
    assert result["result"]["text"] == "private log <script>"
    from dingofs_platform.remote.models import RemoteSession

    with admin.app.state.session_factory() as db:
        row = db.get(RemoteSession, result["id"])
        assert "private log" not in str(row.result)
    assert (
        start(admin, c, "read", service_id="svc1", file_id="/etc/shadow").status_code
        == 422
    )


def test_terminal_confirm_scope_origin_and_close(admin):
    m, c = fixture(admin)
    assert start(admin, c, "terminal", machine_id=m["id"]).status_code == 422
    other = machine(admin, "other")
    assert (
        start(admin, c, "terminal", machine_id=other["id"], confirmed=True).status_code
        == 403
    )
    result = start(admin, c, "terminal", machine_id=m["id"], confirmed=True)
    assert result.status_code == 202, result.text
    sid = result.json()["id"]
    wait(admin, sid, {"ready"})
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect(
            "/api/v1/remote-sessions/" + sid + "/stream",
            headers={"Origin": "https://evil.test"},
        ):
            pass
    with admin.websocket_connect(
        "/api/v1/remote-sessions/" + sid + "/stream",
        headers={"Origin": "http://testserver"},
    ) as ws:
        ws.send_json({"type": "input", "data": "pwd\r"})
        for _ in range(100):
            if FakeJob.instances[-1].sent:
                break
            time.sleep(0.01)
        assert FakeJob.instances[-1].sent[-1]["data"] == "pwd\r"
    wait(admin, sid, {"closed"})
    assert FakeJob.instances[-1].closed


def test_member_cannot_read_admin_machine_or_open_terminal(admin):
    m, c = fixture(admin)
    admin.post(
        "/api/v1/auth/login",
        json={"username": "member", "password": "test-password-123"},
    )
    # Refresh CSRF after replacing the login cookie.
    token = admin.get("/api/v1/auth/me").json()["csrf_token"]
    admin.headers["X-CSRF-Token"] = token
    assert start(admin, c, "files", service_id="svc1").status_code == 403
    assert (
        start(admin, c, "terminal", machine_id=m["id"], confirmed=True).status_code
        == 403
    )
    assert (
        admin.get("/api/v1/clusters/" + c["id"] + "/remote-targets").status_code == 200
    )


def test_machine_revision_and_login_revocation_close_jobs(admin):
    m, c = fixture(admin)
    res = start(admin, c, "terminal", machine_id=m["id"], confirmed=True)
    sid = res.json()["id"]
    wait(admin, sid, {"ready"})
    with admin.app.state.session_factory.begin() as db:
        db.get(Machine, m["id"]).revision += 1
    assert admin.get("/api/v1/remote-sessions/" + sid).json()["state"] == "closed"
    assert FakeJob.instances[-1].closed


def test_terminal_limit_and_release(admin):
    m, c = fixture(admin)
    a = start(admin, c, "terminal", machine_id=m["id"], confirmed=True)
    b = start(admin, c, "terminal", machine_id=m["id"], confirmed=True)
    assert a.status_code == b.status_code == 202
    assert (
        start(admin, c, "terminal", machine_id=m["id"], confirmed=True).status_code
        == 429
    )
    assert admin.delete("/api/v1/remote-sessions/" + a.json()["id"]).status_code == 204
    assert (
        start(admin, c, "terminal", machine_id=m["id"], confirmed=True).status_code
        == 202
    )
