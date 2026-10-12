"""Host aliases never turn ambiguous hosts into an arbitrary SSH target."""

import pytest
from dingofs_platform.inventory.schemas import MachineInput
from pydantic import ValidationError


def test_aliases_are_canonical_and_deduplicated():
    value = MachineInput(
        name="node",
        address="2001:0DB8:0000::1",
        ssh_user="root",
        aliases=["DINGO126.", "dingo126", "dingo126.NOVALOCAL.", "2001:db8::1"],
    )
    assert value.address == "2001:db8::1"
    assert value.aliases == ["dingo126", "dingo126.novalocal", "2001:db8::1"]


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "node..test",
        "-node",
        "node-",
        "node/path",
        "node:22",
        "node name",
        "node\nname",
        "https://node",
        "[::1]",
        "999.1.2.3",
        "a" * 64 + ".test",
        "node%eth0",
        "fe80::1%eth0",
        "a." * 128,
    ],
)
def test_invalid_host_identifiers_are_rejected(value):
    for field in ("address", "aliases"):
        fields = {"name": "node", "address": "node.test", "ssh_user": "root"}
        fields[field] = [value] if field == "aliases" else value
        with pytest.raises(ValidationError):
            MachineInput(**fields)


def test_alias_limit_and_default():
    assert MachineInput(name="node", address="node", ssh_user="root").aliases == []
    with pytest.raises(ValidationError):
        MachineInput(name="node", address="node", ssh_user="root", aliases=["a"] * 33)


def test_api_alias_sync_revision_and_conflicts(admin, app):
    from dingofs_platform.inventory.host_identity import resolve_host

    first = admin.post(
        "/api/v1/machines",
        json={
            "name": "first",
            "address": "172.30.14.126",
            "ssh_user": "root",
            "aliases": ["DINGO126.", "dingo126", "shared"],
        },
    )
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["aliases"] == ["dingo126", "shared"]
    assert first["alias_conflicts"] == {}
    second = admin.post(
        "/api/v1/machines",
        json={
            "name": "second",
            "address": "172.30.14.127",
            "ssh_user": "root",
            "aliases": ["shared"],
        },
    )
    assert second.status_code == 201, second.text
    second = second.json()
    assert second["alias_conflicts"]["shared"][0]["id"] == first["id"]
    with app.state.session_factory() as db:
        assert [m.id for m in resolve_host(db, "DINGO126.")] == [first["id"]]
        assert {m.id for m in resolve_host(db, "shared")} == {first["id"], second["id"]}
        assert resolve_host(db, "unknown") == []
        assert resolve_host(db, "invalid/host") == []
    changed = admin.patch(
        "/api/v1/machines/" + first["id"],
        json={
            "base_revision": first["revision"],
            "address": "2001:0DB8::1",
            "aliases": ["new-name"],
        },
    )
    assert changed.status_code == 200, changed.text
    changed = changed.json()
    assert changed["revision"] == first["revision"] + 1
    with app.state.session_factory() as db:
        assert resolve_host(db, "dingo126") == []
        assert resolve_host(db, "172.30.14.126") == []
        assert [m.id for m in resolve_host(db, "2001:db8:0:0::1")] == [first["id"]]
        assert [m.id for m in resolve_host(db, "shared")] == [second["id"]]
    archived = admin.patch(
        "/api/v1/machines/" + second["id"],
        json={
            "base_revision": second["revision"],
            "archived": True,
        },
    )
    assert archived.status_code == 200, archived.text
    with app.state.session_factory() as db:
        assert resolve_host(db, "shared") == []


def test_api_same_address_ports_remain_ambiguous_and_alias_edit_is_owned(admin, app):
    from dingofs_platform.inventory.host_identity import resolve_host
    from test_asset_permissions import member_client

    with (
        member_client(app, "alias-owner") as owner,
        member_client(app, "alias-other") as other,
    ):
        first = owner.post(
            "/api/v1/machines",
            json={
                "name": "port22",
                "address": "port.test",
                "ssh_user": "root",
                "aliases": ["port.test"],
            },
        ).json()
        second = admin.post(
            "/api/v1/machines",
            json={
                "name": "port23",
                "address": "port.test",
                "ssh_port": 23,
                "ssh_user": "root",
            },
        )
        assert second.status_code == 201, second.text
        with app.state.session_factory() as db:
            assert len(resolve_host(db, "PORT.test.")) == 2
        response = other.patch(
            "/api/v1/machines/" + first["id"],
            json={
                "base_revision": first["revision"],
                "aliases": ["stolen"],
            },
        )
        assert response.status_code == 403
        response = owner.patch(
            "/api/v1/machines/" + first["id"],
            json={
                "base_revision": first["revision"],
                "aliases": ["mine"],
            },
        )
        assert response.status_code == 200, response.text


def test_api_cluster_links_report_missing_and_ambiguous_hosts(admin, app):
    from conftest import register_cluster
    from dingofs_platform.inventory.models import Cluster

    first = admin.post(
        "/api/v1/machines",
        json={
            "name": "manager",
            "address": "172.30.14.126",
            "ssh_user": "root",
            "aliases": ["dingo126", "shared"],
        },
    ).json()
    second = admin.post(
        "/api/v1/machines",
        json={
            "name": "worker",
            "address": "172.30.14.127",
            "ssh_user": "root",
            "aliases": ["shared"],
        },
    )
    assert second.status_code == 201, second.text
    cluster = register_cluster(admin, first)
    with app.state.session_factory.begin() as db:
        row = db.get(Cluster, cluster["id"])
        snapshot = dict(row.status_snapshot)
        services = snapshot["services"]
        snapshot["services"] = [
            {**services[0], "host": host}
            for host in ("DINGO126.", "shared", "missing.test")
        ]
        row.status_snapshot = snapshot
    result = admin.get("/api/v1/clusters/" + cluster["id"])
    assert result.status_code == 200, result.text
    assert result.json()["node_links"] == {"DINGO126.": first["id"]}
    assert result.json()["node_match_states"] == {
        "DINGO126.": "matched",
        "shared": "ambiguous",
        "missing.test": "missing",
    }


def test_lookup_index_handles_alias_address_overlap_and_replacement():
    from dingofs_platform.inventory.host_identity import (
        resolve_host,
        sync_host_identifiers,
    )
    from dingofs_platform.inventory.models import Machine, MachineHostIdentifier
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    Machine.__table__.create(engine)
    MachineHostIdentifier.__table__.create(engine)
    with Session(engine) as db:
        first = Machine(
            name="first",
            address="2001:db8::1",
            ssh_user="root",
            aliases=["2001:0DB8::1", "old"],
        )
        second = Machine(
            name="second", address="elsewhere", ssh_user="root", aliases=["old"]
        )
        db.add_all([first, second])
        db.flush()
        sync_host_identifiers(db, first)
        sync_host_identifiers(db, second)
        assert [m.id for m in resolve_host(db, "2001:0db8:0::1")] == [first.id]
        assert len(resolve_host(db, "old")) == 2
        first.aliases = ["new"]
        sync_host_identifiers(db, first)
        assert [m.id for m in resolve_host(db, "old")] == [second.id]
        assert [m.id for m in resolve_host(db, "NEW.")] == [first.id]
        second.archived = True
        assert resolve_host(db, "old") == []
        assert resolve_host(db, "bad/host") == []
        assert (
            len(
                list(
                    db.scalars(
                        select(MachineHostIdentifier).where(
                            MachineHostIdentifier.machine_id == first.id
                        )
                    )
                )
            )
            == 2
        )
    engine.dispose()


def test_migration_backfills_canonical_addresses_without_changing_connections(
    monkeypatch,
):
    import os
    from datetime import datetime, timezone
    from pathlib import Path
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from dingofs_platform.db import Base
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

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
    values = [
        (str(uuid4()), "first", "DINGO126.", 22, "dingo126"),
        (str(uuid4()), "second", "2001:0DB8::1", 22, "2001:db8::1"),
        (str(uuid4()), "third", "2001:db8::1", 23, "2001:db8::1"),
    ]
    try:
        command.upgrade(config, "f364c58f1da7")
        with engine.begin() as db:
            for id, name, address, port, _ in values:
                db.execute(
                    text("""INSERT INTO machines
                    (id,name,address,ssh_port,ssh_user,credential_ref,tags,maintenance,archived,created_at,updated_at,revision)
                    VALUES (:id,:name,:address,:port,'root','','[]',false,false,:now,:now,7)"""),
                    {
                        "id": id,
                        "name": name,
                        "address": address,
                        "port": port,
                        "now": datetime.now(timezone.utc),
                    },
                )
        command.upgrade(config, "f475d6902eb8")
        with engine.connect() as db:
            for id, _, address, port, expected in values:
                row = (
                    db.execute(text("SELECT * FROM machines WHERE id=:id"), {"id": id})
                    .mappings()
                    .one()
                )
                assert (
                    row["address"],
                    row["ssh_port"],
                    row["revision"],
                    row["aliases"],
                ) == (address, port, 7, [])
                assert (
                    db.scalar(
                        text(
                            "SELECT identifier FROM machine_host_identifiers WHERE machine_id=:id"
                        ),
                        {"id": id},
                    )
                    == expected
                )
        command.downgrade(config, "f364c58f1da7")
        command.upgrade(config, "f475d6902eb8")
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM machine_host_identifiers")) == 3
    finally:
        Base.metadata.drop_all(engine)
        with engine.begin() as db:
            db.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()
