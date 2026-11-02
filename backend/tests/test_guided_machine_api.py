from cryptography.fernet import Fernet
from sqlalchemy import func, select

from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.ssh_transport import CollectionError


SECRET = "  guided-secret $(id)  "


def payload(**changes):
    value = {
        "name": "guided-node",
        "address": "guided-node.test",
        "ssh_port": 22,
        "ssh_user": "jenkins",
        "ssh_password": SECRET,
    }
    value.update(changes)
    return value


def counts(app):
    with app.state.session_factory() as db:
        return (
            db.scalar(select(func.count()).select_from(Machine)),
            db.scalar(select(func.count()).select_from(AuditEvent)),
        )


def configure(app, transport):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    app.state.hardware_transport = transport


def test_guided_machine_requires_five_fields(admin, app):
    configure(app, lambda *args, **kwargs: {})
    for field in ("name", "address", "ssh_user", "ssh_password"):
        request = payload()
        request.pop(field)
        response = admin.post("/api/v1/guided/machines", json=request)
        assert response.status_code == 422, (field, response.text)
    assert counts(app)[0] == 0


def test_guided_machine_preserves_password_whitespace_for_transport(admin, app):
    seen = []

    def reject(config, *args, **kwargs):
        seen.append(config.password)
        raise CollectionError("authentication_failed")

    configure(app, reject)
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 422, response.text
    assert seen == [SECRET]
    assert SECRET not in response.text


def test_guided_machine_auth_failure_persists_nothing(admin, app):
    def reject(*args, **kwargs):
        raise CollectionError("authentication_failed")

    configure(app, reject)
    before = counts(app)
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "authentication_failed"
    assert "SSH 认证失败" in response.json()["message"]
    assert SECRET not in response.text
    assert counts(app) == before


def test_guided_machine_connection_failure_is_classified(admin, app):
    def reject(*args, **kwargs):
        raise CollectionError("connection_failed")

    configure(app, reject)
    before = counts(app)
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "connection_failed"
    assert "地址、端口和网络" in response.json()["message"]
    assert counts(app) == before


def test_guided_machine_total_hardware_failure_persists_nothing(admin, app):
    configure(app, lambda *args, **kwargs: {})
    before = counts(app)
    response = admin.post("/api/v1/guided/machines", json=payload())
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "hardware_collection_failed"
    assert counts(app) == before
