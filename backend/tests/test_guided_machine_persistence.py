import json
import threading
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.auth.models import Session
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.ssh_transport import CommandResult

from test_guided_machine_api import SECRET, configure, counts, payload


def successful_outputs():
    from test_hardware import sample

    return sample.__wrapped__()


def test_guided_machine_success_saves_encrypted_password_and_snapshot(admin, app):
    configure(app, lambda *args, **kwargs: successful_outputs())
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["collection_status"] == "success"
    assert body["hardware_info"]["cpu"]["logical_cores"] == 8
    assert body["last_success_at"] and body["last_attempt_at"]
    assert body["has_ssh_password"] is True
    with app.state.session_factory() as db:
        row = db.get(Machine, body["id"])
        assert row.ssh_password_ciphertext != SECRET
        assert (
            decrypt_password(
                row.ssh_password_ciphertext,
                app.state.settings.credential_encryption_key,
            )
            == SECRET
        )


def test_guided_machine_partial_succeeds_with_warning(admin, app):
    configure(
        app,
        lambda *args, **kwargs: {
            "memory": CommandResult("MemTotal: 1024 kB", "", 0)
        },
    )
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["collection_status"] == "partial"
    assert body["hardware_info"]["memory"]["total_bytes"] == 1048576
    assert body["hardware_info"]["warnings"]


def test_guided_machine_duplicate_name_or_endpoint_returns_409(admin, app):
    configure(app, lambda *args, **kwargs: successful_outputs())
    first = admin.post("/api/v1/guided/machines", json=payload())
    assert first.status_code == 201, first.text
    same_name = admin.post(
        "/api/v1/guided/machines",
        json=payload(address="another-guided-node.test"),
    )
    assert same_name.status_code == 409, same_name.text
    same_endpoint = admin.post(
        "/api/v1/guided/machines", json=payload(name="another-guided-node")
    )
    assert same_endpoint.status_code == 409, same_endpoint.text
    assert counts(app)[0] == 1


def test_guided_machine_reauthenticates_after_probe(admin, app):
    def revoke(*args, **kwargs):
        with app.state.session_factory.begin() as db:
            db.execute(delete(Session))
        return successful_outputs()

    configure(app, revoke)
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 401, response.text
    assert counts(app)[0] == 0


def test_guided_machine_audit_and_response_exclude_password(admin, app):
    configure(app, lambda *args, **kwargs: successful_outputs())
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 201, response.text
    assert SECRET not in response.text
    assert "ssh_password_ciphertext" not in response.text
    with app.state.session_factory() as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.entity == "machines/" + response.json()["id"])
            )
        )
        encoded = json.dumps([event.detail for event in events])
        assert len(events) == 1
        assert SECRET not in encoded and "ssh_password" not in encoded


def test_guided_machine_concurrent_duplicate_commits_once(app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    barrier = threading.Barrier(2)

    def transport(*args, **kwargs):
        barrier.wait(timeout=5)
        return successful_outputs()

    app.state.hardware_transport = transport

    def submit(index):
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "test-password-123"},
            )
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            return client.post(
                "/api/v1/guided/machines",
                json=payload(name=f"race-{index}", address="race.test"),
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(submit, (1, 2)))
    assert statuses == [201, 409]
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Machine)) == 1
