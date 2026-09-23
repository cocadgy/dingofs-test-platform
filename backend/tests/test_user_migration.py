"""Upgrade an existing account without inventing an email or discarding its password."""

import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from fastapi.testclient import TestClient
from dingofs_platform.db import Base
from dingofs_platform.auth.service import hasher
from dingofs_platform.app import create_app
from dingofs_platform.settings import Settings


def test_legacy_account_survives_upgrade_and_can_supply_email(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert parsed.host in ("localhost", "127.0.0.1") and parsed.database.endswith(
        "_test"
    )
    monkeypatch.setenv("PLATFORM_DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS alembic_version"))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "b414037149a5")
    id = str(uuid4())
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users(id,username,password_hash,role,disabled,created_at,updated_at,revision) VALUES (:id,:name,:hash,:role,false,:now,:now,1)"
            ),
            {
                "id": id,
                "name": "legacy",
                "hash": hasher.hash("legacy-password-123"),
                "role": "admin",
                "now": now,
            },
        )
    machine_id = str(uuid4())
    context_id = str(uuid4())
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO machines(id,name,address,ssh_port,ssh_user,credential_ref,tags,maintenance,archived,created_at,updated_at,revision) VALUES (:id,'legacy-node','node.test',22,'root','legacy-ref','[]',false,false,:now,:now,1)"
            ),
            {"id": machine_id, "now": now},
        )
        c.execute(
            text(
                "INSERT INTO management_contexts(id,name,machine_id,os_user,dingo_path,config_dir,credential_ref,archived,created_at,updated_at,revision) VALUES (:id,'legacy-context',:mid,'root','/bin/dingo','/root/.dingo','',false,:now,:now,1)"
            ),
            {"id": context_id, "mid": machine_id, "now": now},
        )
    command.upgrade(config, "head")
    command.check(config)
    app = create_app(Settings(database_url=url, cookie_secure=False))
    try:
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/auth/login",
                json={"username": "legacy", "password": "legacy-password-123"},
            )
            assert (
                r.status_code == 200
                and r.json()["email"] is None
                and r.json()["id"] == id
            )
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
            assert (
                c.patch(
                    "/api/v1/auth/profile",
                    json={
                        "email": "legacy@example.com",
                        "current_password": "legacy-password-123",
                    },
                ).status_code
                == 200
            )
            assert c.get("/api/v1/auth/me").json()["email"] == "legacy@example.com"
            machine = c.get("/api/v1/machines/" + machine_id).json()
            assert machine["credential_ref"] == "legacy-ref"
            assert (
                machine["has_ssh_password"] is False
                and machine["hardware_info"] is None
            )
            assert machine["collection_status"] == "never"
            assert c.get("/api/v1/management-contexts/" + context_id).status_code == 404
            with engine.connect() as db:
                assert (
                    db.scalar(
                        text("SELECT machine_id FROM management_contexts WHERE id=:id"),
                        {"id": context_id},
                    )
                    == machine_id
                )
    finally:
        Base.metadata.drop_all(engine)
        with engine.begin() as c:
            c.execute(text("DROP TABLE alembic_version"))
        engine.dispose()
        app.state.engine.dispose()
