from pathlib import Path
from cryptography.fernet import Fernet
from dingofs_platform.clusters.transport import (
    ClusterCommandResult,
    ExecutionIdentity,
    AuthenticationRequired,
)

RAW = (Path(__file__).parent / "fixtures/dingo/cluster-status-main.txt").read_text()


def setup_machine(admin, app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    r = admin.post(
        "/api/v1/machines",
        json={
            "name": "node",
            "address": "node.test",
            "ssh_user": "test",
            "ssh_password": "SSH-sentinel",
        },
    )
    assert r.status_code == 201
    return r.json()


def transport(config, cmd, **kwargs):
    return ClusterCommandResult(
        ExecutionIdentity(cmd.target_user, "/home/" + cmd.target_user, "/bin/dingo"),
        "main-dingofs\ntest-dingofs\n"
        if cmd.kind == "discover"
        else RAW.replace("main-dingofs", cmd.cluster_name),
        "",
        0,
    )


def discover(admin, m, user="root"):
    r = admin.post(
        "/api/v1/cluster-discoveries",
        json={
            "machine_id": m["id"],
            "machine_revision": m["revision"],
            "target_user": user,
        },
    )
    assert r.status_code == 202, r.text
    return admin.get("/api/v1/cluster-operations/" + r.json()["id"]).json()


def test_discover_import_and_same_name_users(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    assert op["state"] == "succeeded"
    r = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["created"][0]["id"]
    assert (
        admin.post(
            "/api/v1/cluster-discoveries/" + op["id"] + "/import",
            json={"names": ["main-dingofs"]},
        ).json()["existing"][0]["id"]
        == cid
    )
    op2 = discover(admin, m, "other")
    assert (
        admin.post(
            "/api/v1/cluster-discoveries/" + op2["id"] + "/import",
            json={"names": ["main-dingofs"]},
        ).status_code
        == 200
    )
    assert admin.get("/api/v1/clusters/overview").json()["total"] == 2
    detail = admin.get("/api/v1/clusters/" + cid).json()
    assert detail["status_snapshot"]["service_count"] == 10
    assert admin.post("/api/v1/clusters", json={}).status_code == 422


def test_password_challenge_and_no_persistence(admin, app):
    m = setup_machine(admin, app)

    def auth(config, cmd, **kw):
        if kw.get("password") != "sudo-SENTINEL":
            raise AuthenticationRequired("test")
        return transport(config, cmd, **kw)

    app.state.cluster_transport = auth
    op = discover(admin, m)
    assert op["state"] == "needs_password" and op["auth_account"] == "test"
    result = admin.post(
        "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
        json={"challenge": op["challenge"], "password": "sudo-SENTINEL"},
    )
    assert result.status_code == 200 and result.json()["state"] == "succeeded", (
        result.text
    )
    assert "sudo-SENTINEL" not in result.text
    assert (
        admin.post(
            "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
            json={"challenge": op["challenge"], "password": "sudo-SENTINEL"},
        ).status_code
        == 409
    )


def test_failed_refresh_keeps_snapshot(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    cid = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()["created"][0]["id"]
    before = admin.get("/api/v1/clusters/" + cid).json()

    def fail(*args, **kw):
        raise RuntimeError("secret")

    app.state.cluster_transport = fail
    assert (
        admin.post(
            "/api/v1/clusters/" + cid + "/refresh-status",
            json={"base_revision": before["revision"]},
        ).status_code
        == 202
    )
    after = admin.get("/api/v1/clusters/" + cid).json()
    assert (
        after["status_snapshot"] == before["status_snapshot"]
        and after["status_success_at"] == before["status_success_at"]
    )
    assert after["status_attempt_state"] == "failed" and "secret" not in str(after)
