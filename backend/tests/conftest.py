import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from dingofs_platform.app import create_app
from dingofs_platform.settings import Settings
from dingofs_platform.db import Base
from dingofs_platform.auth.service import create_user


@pytest.fixture
def app():
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert parsed.database.endswith("_test") and parsed.host in (
        "127.0.0.1",
        "localhost",
    )
    app = create_app(Settings(database_url=url, cookie_secure=False))
    Base.metadata.drop_all(app.state.engine)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        create_user(
            db, "admin", "test-password-123", "admin", email="admin@example.com"
        )
        create_user(
            db, "member", "test-password-123", "member", email="member@example.com"
        )
    yield app
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    result = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password-123"},
    )
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return client


def machine(client, name="node1"):
    r = client.post(
        "/api/v1/machines",
        json={"name": name, "address": name + ".test", "ssh_user": "test"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def register_cluster(client, m, name="c1", user="test", display="cluster1"):
    from cryptography.fernet import Fernet
    from pathlib import Path
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.credentials import encrypt_password
    from dingofs_platform.clusters.transport import (
        ClusterCommandResult,
        ExecutionIdentity,
    )

    app = client.app
    if not app.state.settings.credential_encryption_key:
        app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    with app.state.session_factory.begin() as db:
        db.get(Machine, m["id"]).ssh_password_ciphertext = encrypt_password(
            "test-secret", app.state.settings.credential_encryption_key
        )
    raw = (Path(__file__).parent / "fixtures/dingo/cluster-status-main.txt").read_text()
    old = getattr(app.state, "cluster_transport", None)

    def transport(config, cmd, **kw):
        return ClusterCommandResult(
            ExecutionIdentity(
                cmd.target_user, "/home/" + cmd.target_user, "/opt/dingo"
            ),
            name + "\n"
            if cmd.kind == "discover"
            else raw.replace("main-dingofs", cmd.cluster_name),
            "",
            0,
        )

    app.state.cluster_transport = transport
    try:
        op = client.post(
            "/api/v1/cluster-discoveries",
            json={
                "machine_id": m["id"],
                "machine_revision": m["revision"],
                "target_user": user,
            },
        )
        assert op.status_code == 202, op.text
        result = client.post(
            "/api/v1/cluster-discoveries/" + op.json()["id"] + "/import",
            json={"names": [name]},
        )
        assert result.status_code == 200, result.text
        cid = (result.json()["created"] + result.json()["existing"])[0]["id"]
        # Preserve the legacy test fixture's initial revision and display alias.
        from dingofs_platform.inventory.models import Cluster

        with app.state.session_factory.begin() as db:
            row = db.get(Cluster, cid)
            row.name = display
        return client.get("/api/v1/clusters/" + cid).json()
    finally:
        if old is None:
            del app.state.cluster_transport
        else:
            app.state.cluster_transport = old


def linked(client):
    m = machine(client)
    cluster = register_cluster(client, m)
    e = client.post(
        "/api/v1/environments",
        json={"name": "env1", "cluster_id": cluster["id"], "machine_ids": [m["id"]]},
    ).json()
    return m, cluster, e
