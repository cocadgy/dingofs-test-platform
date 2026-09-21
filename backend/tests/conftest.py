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
        create_user(db, "admin", "test-password-123", "admin")
        create_user(db, "member", "test-password-123", "member")
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


def linked(client):
    m = machine(client)
    c = client.post(
        "/api/v1/management-contexts",
        json={
            "name": "context1",
            "machine_id": m["id"],
            "os_user": "test",
            "dingo_path": "/opt/dingo",
            "config_dir": "/home/test/.dingo",
        },
    ).json()
    cluster = client.post(
        "/api/v1/clusters",
        json={
            "name": "cluster1",
            "context_id": c["id"],
            "external_name": "c1",
            "machine_ids": [m["id"]],
        },
    ).json()
    e = client.post(
        "/api/v1/environments",
        json={"name": "env1", "cluster_id": cluster["id"], "machine_ids": [m["id"]]},
    ).json()
    return m, c, cluster, e
