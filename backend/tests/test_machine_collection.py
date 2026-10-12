from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete
from dingofs_platform.auth.models import Session
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.ssh_transport import CollectionError


@pytest.fixture
def node(admin, app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    app.state.hardware_transport = lambda *a, **k: {}
    r = admin.post(
        "/api/v1/machines",
        json=dict(
            name="node", address="node.test", ssh_user="root", ssh_password="private"
        ),
    )
    assert r.status_code == 201
    return admin.get("/api/v1/machines/" + r.json()["id"]).json()


def refresh(admin, node):
    return admin.post(
        "/api/v1/machines/" + node["id"] + "/refresh-hardware",
        json={"base_revision": node["revision"]},
    )


def test_failed_refresh_preserves_last_success(admin, app, node):
    old = {"schema_version": 1, "cpu": {"logical_cores": 8}}
    with app.state.session_factory.begin() as db:
        db.get(Machine, node["id"]).hardware_info = old

    def fail(*args, **kwargs):
        raise CollectionError("authentication_failed")

    app.state.hardware_transport = fail
    r = refresh(admin, node)
    assert r.status_code == 200, r.text
    assert r.json()["collection_status"] == "failed"
    assert r.json()["hardware_info"] == old
    assert "private" not in r.text


def test_partial_is_separate_snapshot(admin, app, node):
    from dingofs_platform.inventory.ssh_transport import CommandResult

    app.state.hardware_transport = lambda *a, **k: {
        "memory": CommandResult("MemTotal: 1024 kB", "", 0)
    }
    r = refresh(admin, node)
    assert r.status_code == 200, r.text
    assert r.json()["collection_status"] == "partial"
    assert r.json()["hardware_info"] is None
    assert r.json()["last_attempt_info"]["memory"]["total_bytes"] == 1048576


def test_revision_change_rejects_old_snapshot(admin, app, node):
    def mutate(*a, **k):
        with app.state.session_factory.begin() as db:
            m = db.get(Machine, node["id"])
            m.ssh_user = "changed"
            m.revision += 1
        return {}

    app.state.hardware_transport = mutate
    r = refresh(admin, node)
    assert r.status_code == 409, r.text
    after = admin.get("/api/v1/machines/" + node["id"]).json()
    assert after["collection_status"] == "interrupted"
    assert after["hardware_info"] is None


def test_expired_token_can_retry_and_live_token_conflicts(admin, app, node):
    with app.state.session_factory.begin() as db:
        m = db.get(Machine, node["id"])
        m.collection_status = "collecting"
        m.collection_token = str(uuid4())
        m.collection_expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    assert refresh(admin, node).status_code == 409
    with app.state.session_factory.begin() as db:
        db.get(Machine, node["id"]).collection_expires_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
    assert (
        admin.get("/api/v1/machines/" + node["id"]).json()["collection_status"]
        == "interrupted"
    )
    app.state.hardware_transport = lambda *a, **k: {}
    assert refresh(admin, node).status_code == 200


def test_new_token_cannot_be_overwritten_by_old_worker(admin, app, node):
    token = str(uuid4())

    def replace(*a, **k):
        with app.state.session_factory.begin() as db:
            db.get(Machine, node["id"]).collection_token = token
        return {}

    app.state.hardware_transport = replace
    assert refresh(admin, node).status_code == 409
    with app.state.session_factory() as db:
        assert db.get(Machine, node["id"]).collection_token == token


def test_revoked_actor_cannot_publish_snapshot(admin, app, node):
    def revoke(*a, **k):
        with app.state.session_factory.begin() as db:
            db.execute(delete(Session))
        return {}

    app.state.hardware_transport = revoke
    assert refresh(admin, node).status_code == 401
    with app.state.session_factory() as db:
        m = db.get(Machine, node["id"])
        assert m.hardware_info is None


def test_refresh_permissions_csrf_archive_and_revision(admin, app, node):
    app.state.hardware_transport = lambda *a, **k: pytest.fail("should not connect")
    assert refresh(admin, {**node, "revision": 99}).status_code == 409
    with app.state.session_factory.begin() as db:
        db.get(Machine, node["id"]).archived = True
    assert refresh(admin, node).status_code == 409
    del admin.headers["X-CSRF-Token"]
    assert refresh(admin, node).status_code == 403
    login = admin.post(
        "/api/v1/auth/login",
        json={"username": "member", "password": "test-password-123"},
    )
    admin.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert refresh(admin, node).status_code == 403


def test_success_updates_snapshot_time_revision_and_audit(admin, app, node):
    from test_hardware import sample

    outputs = sample.__wrapped__()
    app.state.hardware_transport = lambda *a, **k: outputs
    response = refresh(admin, node)
    assert response.status_code == 200, response.text
    m = response.json()
    assert m["collection_status"] == "success"
    assert m["last_success_at"] and m["last_attempt_at"]
    assert m["hardware_info"]["cpu"]["logical_cores"] == 8
    assert m["revision"] == node["revision"] + 1
    assert "collection_token" not in m and "private" not in response.text
