"""Existing shared contexts migrate without changing cluster/environment identities."""

import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from dingofs_platform.db import Base


def test_shared_context_migration_preserves_links_and_config(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert parsed.host in ("localhost", "127.0.0.1") and parsed.database.endswith(
        "_test"
    )
    monkeypatch.setenv("PLATFORM_DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as db:
        db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    mid, cid, a, b, env, version = [str(uuid4()) for _ in range(6)]
    now = datetime.now(timezone.utc)
    try:
        command.upgrade(config, "e9f218b704c2")
        with engine.begin() as db:
            db.execute(
                text("""INSERT INTO machines(id,name,address,ssh_port,ssh_user,credential_ref,tags,maintenance,archived,created_at,updated_at,revision)
                VALUES (:id,'node','node.test',22,'root','','[]',false,false,:now,:now,1)"""),
                dict(id=mid, now=now),
            )
            db.execute(
                text("""INSERT INTO management_contexts(id,name,machine_id,os_user,dingo_path,config_dir,credential_ref,archived,created_at,updated_at,revision)
                VALUES (:id,'shared',:mid,'root','/bin/dingo','/root/.dingo','key-ref',false,:now,:now,1)"""),
                dict(id=cid, mid=mid, now=now),
            )
            for id, name, archived in [(a, "first", False), (b, "second", True)]:
                db.execute(
                    text("""INSERT INTO clusters(id,name,context_id,external_name,management_scope,observed_state,archived,created_at,updated_at,revision)
                    VALUES (:id,:name,:cid,:name,'registered','unknown',:archived,:now,:now,7)"""),
                    dict(id=id, name=name, cid=cid, archived=archived, now=now),
                )
            db.execute(
                text(
                    "INSERT INTO cluster_machines(cluster_id,machine_id) VALUES (:id,:mid)"
                ),
                dict(id=a, mid=mid),
            )
            db.execute(
                text("""INSERT INTO environments(id,name,cluster_id,enabled,archived,created_at,updated_at,revision)
                VALUES (:id,'env',:cid,true,false,:now,:now,1)"""),
                dict(id=env, cid=a, now=now),
            )
            db.execute(
                text("""INSERT INTO config_versions(id,owner_kind,owner_id,version,yaml_text,sha256,author,created_at,updated_at,revision)
                VALUES (:id,'cluster',:cid,1,'config: preserved','test-sha','test-author',:now,:now,1)"""),
                dict(id=version, cid=a, now=now),
            )
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as db:
            rows = (
                db.execute(text("SELECT * FROM clusters ORDER BY name"))
                .mappings()
                .all()
            )
            assert len(rows) == 2 and {r["id"] for r in rows} == {a, b}
            for row in rows:
                assert row["management_machine_id"] == mid and row["os_user"] == "root"
                assert (
                    row["dingo_path"] == "/bin/dingo"
                    and row["config_dir"] == "/root/.dingo"
                )
                assert row["credential_ref"] == "key-ref" and row["revision"] == 7
                assert "context_id" not in row
                assert row["creator_id"] is None
            assert rows[1]["archived"] is True
            assert (
                db.scalar(
                    text("SELECT cluster_id FROM environments WHERE id=:id"),
                    dict(id=env),
                )
                == a
            )
            assert (
                db.scalar(
                    text(
                        "SELECT machine_id FROM cluster_machines WHERE cluster_id=:id"
                    ),
                    dict(id=a),
                )
                == mid
            )
            assert (
                db.scalar(
                    text("SELECT yaml_text FROM config_versions WHERE id=:id"),
                    dict(id=version),
                )
                == "config: preserved"
            )
        command.downgrade(config, "e9f218b704c2")
        with engine.connect() as db:
            assert (
                db.scalar(
                    text("SELECT context_id FROM clusters WHERE id=:id"), dict(id=a)
                )
                == cid
            )
        command.upgrade(config, "head")
        command.check(config)
    finally:
        Base.metadata.drop_all(engine)
        with engine.begin() as db:
            db.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()
