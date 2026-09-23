from sqlalchemy import select
from datetime import timedelta
from fastapi.testclient import TestClient
from dingofs_platform.clusters.models import ClusterOperation
from dingofs_platform.clusters.operations import now
from dingofs_platform.clusters.transport import AuthenticationRequired
from dingofs_platform.inventory.models import Machine, Cluster
from test_cluster_discovery import setup_machine, transport, discover


def auth_transport(*args, **kw):
    raise AuthenticationRequired("test")


def test_foreign_actor_stale_and_expired_challenge(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = auth_transport
    op = discover(admin, m)
    with TestClient(app) as other:
        r = other.post(
            "/api/v1/auth/login",
            json={"username": "member", "password": "test-password-123"},
        )
        other.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        assert other.get("/api/v1/cluster-operations/" + op["id"]).status_code == 403
        assert (
            other.post(
                "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
                json={"challenge": op["challenge"], "password": "x"},
            ).status_code
            == 403
        )
        assert (
            other.post(
                "/api/v1/cluster-discoveries",
                json={
                    "machine_id": m["id"],
                    "machine_revision": 1,
                    "target_user": "root",
                },
            ).status_code
            == 403
        )
    with app.state.session_factory.begin() as db:
        db.get(Machine, m["id"]).revision += 1
    assert (
        admin.post(
            "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
            json={"challenge": op["challenge"], "password": "x"},
        ).status_code
        == 409
    )
    with app.state.session_factory.begin() as db:
        db.get(ClusterOperation, op["id"]).expires_at = now() - timedelta(seconds=1)
    assert (
        admin.get("/api/v1/cluster-operations/" + op["id"]).json()["state"]
        == "interrupted"
    )


def test_wrong_password_limited_cancel_and_secret_not_stored(admin, app, caplog):
    m = setup_machine(admin, app)
    app.state.cluster_transport = auth_transport
    op = discover(admin, m)
    for i in range(3):
        r = admin.post(
            "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
            json={"challenge": op["challenge"], "password": "SUDO-secret-sentinel"},
        )
        assert r.status_code == 200
        r = r.json()
        if i < 2:
            assert r["challenge"] != op["challenge"]
        op = r
    assert op["state"] == "failed" and op["error_code"] == "auth_limit"
    with app.state.session_factory() as db:
        row = db.get(ClusterOperation, op["id"])
        assert "SUDO-secret-sentinel" not in str(
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
        )
    assert "SUDO-secret-sentinel" not in caplog.text
    op = discover(admin, m)
    assert (
        admin.post("/api/v1/cluster-operations/" + op["id"] + "/cancel").json()["state"]
        == "cancelled"
    )
    assert (
        admin.post(
            "/api/v1/cluster-operations/" + op["id"] + "/authenticate",
            json={"challenge": op["challenge"], "password": "x"},
        ).status_code
        == 409
    )


def test_stale_result_and_user_revocation_cannot_import(admin, app):
    m = setup_machine(admin, app)

    def stale(config, cmd, **kw):
        with app.state.session_factory.begin() as db:
            db.get(Machine, m["id"]).revision += 1
        return transport(config, cmd, **kw)

    app.state.cluster_transport = stale
    op = discover(admin, m)
    assert op["state"] == "failed" and op["error_code"] == "stale"
    assert (
        admin.post(
            "/api/v1/cluster-discoveries/" + op["id"] + "/import",
            json={"names": ["main-dingofs"]},
        ).status_code
        == 409
    )


def test_import_selection_scope_and_legacy_rebind(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    with app.state.session_factory.begin() as db:
        c = Cluster(
            name="legacy",
            external_name="main-dingofs",
            management_machine_id=m["id"],
            os_user="root",
            dingo_path="/old/dingo",
            config_dir="/custom",
            credential_ref="",
        )
        db.add(c)
        db.flush()
        cid = c.id
    op = discover(admin, m)
    assert (
        admin.post(
            "/api/v1/cluster-discoveries/" + op["id"] + "/import",
            json={"names": ["fake"]},
        ).status_code
        == 422
    )
    result = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()
    assert result["needs_confirmation"][0]["candidates"][0]["id"] == cid
    assert (
        admin.post(
            "/api/v1/clusters/" + cid + "/refresh-status", json={"base_revision": 1}
        ).status_code
        == 409
    )
    r = admin.post(
        "/api/v1/clusters/" + cid + "/rebind",
        json={"base_revision": 1, "discovery_id": op["id"], "name": "main-dingofs"},
    )
    assert (
        r.status_code == 200
        and r.json()["id"] == cid
        and r.json()["binding_state"] == "verified"
    )


def test_invalid_output_and_target_mismatch_never_replace_snapshot(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    cid = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()["created"][0]["id"]
    before = admin.get("/api/v1/clusters/" + cid).json()
    from dataclasses import replace

    def wrong(config, cmd, **kw):
        return replace(transport(config, cmd, **kw), stdout="broken output")

    app.state.cluster_transport = wrong
    r = admin.post(
        "/api/v1/clusters/" + cid + "/refresh-status",
        json={"base_revision": before["revision"]},
    )
    assert r.status_code == 202
    after = admin.get("/api/v1/clusters/" + cid).json()
    assert (
        after["status_snapshot"] == before["status_snapshot"]
        and after["status_error_code"] == "invalid_header"
    )


def test_pending_auth_is_reused_for_same_actor_refresh(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    cid = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()["created"][0]["id"]
    app.state.cluster_transport = auth_transport
    first = admin.post(
        "/api/v1/clusters/" + cid + "/refresh-status", json={"base_revision": 1}
    ).json()
    second = admin.post(
        "/api/v1/clusters/" + cid + "/refresh-status", json={"base_revision": 1}
    ).json()
    assert second["id"] == first["id"]


def test_expired_and_cancelled_status_is_not_left_collecting(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    cid = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()["created"][0]["id"]
    app.state.cluster_transport = auth_transport
    status_op = admin.post(
        "/api/v1/clusters/" + cid + "/refresh-status", json={"base_revision": 1}
    ).json()
    admin.post("/api/v1/cluster-operations/" + status_op["id"] + "/cancel")
    assert (
        admin.get("/api/v1/clusters/" + cid).json()["status_attempt_state"]
        == "cancelled"
    )
    status_op = admin.post(
        "/api/v1/clusters/" + cid + "/refresh-status", json={"base_revision": 1}
    ).json()
    with app.state.session_factory.begin() as db:
        db.get(ClusterOperation, status_op["id"]).expires_at = now() - timedelta(
            seconds=1
        )
    assert (
        admin.get("/api/v1/clusters/" + cid).json()["status_attempt_state"]
        == "interrupted"
    )


def test_concurrency_limit_and_cancel_rejects_late_result(admin, app):
    import threading, time

    m = setup_machine(admin, app)
    gate = threading.Event()
    entered = []
    responses = []

    def slow(config, cmd, **kw):
        entered.append(cmd.target_user)
        assert gate.wait(5)
        return transport(config, cmd, **kw)

    app.state.cluster_transport = slow

    def start(user):
        responses.append(
            admin.post(
                "/api/v1/cluster-discoveries",
                json={
                    "machine_id": m["id"],
                    "machine_revision": 1,
                    "target_user": user,
                },
            )
        )

    workers = [threading.Thread(target=start, args=(u,)) for u in ("a", "b")]
    try:
        for w in workers:
            w.start()
        deadline = time.monotonic() + 4
        while len(entered) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(entered) == 2
        assert (
            admin.post(
                "/api/v1/cluster-discoveries",
                json={"machine_id": m["id"], "machine_revision": 1, "target_user": "c"},
            ).status_code
            == 409
        )
        with app.state.session_factory() as db:
            ids = list(db.scalars(select(ClusterOperation.id)))
        for id in ids:
            assert (
                admin.post("/api/v1/cluster-operations/" + id + "/cancel").status_code
                == 200
            )
    finally:
        gate.set()
        for w in workers:
            w.join(6)
    with app.state.session_factory() as db:
        assert all(
            o.state == "cancelled" and o.result is None
            for o in db.scalars(select(ClusterOperation))
        )


def test_revoked_actor_during_execution_discards_result(admin, app):
    from sqlalchemy import delete
    from dingofs_platform.auth.models import Session

    m = setup_machine(admin, app)

    def revoked(config, cmd, **kw):
        with app.state.session_factory.begin() as db:
            db.execute(delete(Session))
        return transport(config, cmd, **kw)

    app.state.cluster_transport = revoked
    r = admin.post(
        "/api/v1/cluster-discoveries",
        json={"machine_id": m["id"], "machine_revision": 1, "target_user": "root"},
    )
    assert r.status_code == 202
    with app.state.session_factory() as db:
        op = db.get(ClusterOperation, r.json()["id"])
        assert op.state == "failed" and op.error_code == "stale" and op.result is None


def test_unreadable_saved_credential_is_reported_as_failed_operation(admin, app):
    from cryptography.fernet import Fernet

    m = setup_machine(admin, app)
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    r = admin.post(
        "/api/v1/cluster-discoveries",
        json={"machine_id": m["id"], "machine_revision": 1, "target_user": "root"},
    )
    assert r.status_code == 202
    op = admin.get("/api/v1/cluster-operations/" + r.json()["id"]).json()
    assert op["state"] == "failed" and op["error_code"] == "credential_unavailable"
