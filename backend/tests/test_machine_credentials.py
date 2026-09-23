import json
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.audit.models import AuditEvent


def test_password_roundtrip_preserves_spaces():
    from dingofs_platform.inventory.credentials import (
        encrypt_password,
        decrypt_password,
    )

    key = Fernet.generate_key().decode()
    encrypted = encrypt_password(" secret ", key)
    assert encrypted != " secret "
    assert decrypt_password(encrypted, key) == " secret "
    for bad in ["", "bad-key", Fernet.generate_key().decode()]:
        with pytest.raises(Problem):
            decrypt_password(encrypted, bad)


def test_password_crud_never_discloses_secret(admin, app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    r = admin.post(
        "/api/v1/machines",
        json=dict(
            name="node", address="node", ssh_user="root", ssh_password=" secret "
        ),
    )
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["has_ssh_password"] is True
    url = "/api/v1/machines/" + m["id"]
    with app.state.session_factory() as db:
        cipher = db.get(Machine, m["id"]).ssh_password_ciphertext
        assert cipher and cipher != " secret "
    for response in [r, admin.get(url), admin.get("/api/v1/machines")]:
        assert " secret " not in response.text and cipher not in response.text
        assert "ssh_password_ciphertext" not in response.text
    for changes in [dict(name="renamed"), dict(ssh_password="")]:
        r = admin.patch(url, json={"base_revision": m["revision"], **changes})
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["has_ssh_password"]
    r = admin.patch(
        url,
        json=dict(
            base_revision=m["revision"], ssh_password="new", clear_ssh_password=True
        ),
    )
    assert r.status_code == 422
    r = admin.patch(
        url, json=dict(base_revision=m["revision"], clear_ssh_password=True)
    )
    assert r.status_code == 200 and not r.json()["has_ssh_password"]
    with app.state.session_factory() as db:
        assert db.get(Machine, m["id"]).ssh_password_ciphertext is None
        assert " secret " not in json.dumps(
            [e.detail for e in db.scalars(select(AuditEvent))]
        )


def test_password_requires_configured_key(admin):
    r = admin.post(
        "/api/v1/machines",
        json=dict(name="n", address="n", ssh_user="u", ssh_password="private"),
    )
    assert r.status_code == 503 and "private" not in r.text
    r = admin.post("/api/v1/machines", json=dict(name="n", address="n", ssh_user="u"))
    assert r.status_code == 201 and not r.json()["has_ssh_password"]
