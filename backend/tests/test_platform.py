from sqlalchemy import select, update
from conftest import machine, linked


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200


def test_database_down_is_not_ready(client, app):
    from sqlalchemy import create_engine

    old = app.state.engine
    app.state.engine = create_engine(
        "postgresql+psycopg://x:x@127.0.0.1:1/absent",
        connect_args={"connect_timeout": 1},
    )
    assert client.get("/health/ready").status_code == 503
    app.state.engine.dispose()
    app.state.engine = old


def test_anonymous_cannot_read_assets(client):
    assert client.get("/api/v1/machines").status_code == 401


def test_wrong_password_and_extra_role_rejected(client):
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "username": "member",
                "password": "test-password-123",
                "role": "admin",
            },
        ).status_code
        == 422
    )


def test_logout_invalidates_saved_session(admin):
    cookie = admin.cookies.get("session")
    assert admin.post("/api/v1/auth/logout").status_code == 204
    admin.cookies.set("session", cookie)
    assert admin.get("/api/v1/auth/me").status_code == 401


def test_csrf_required(admin):
    del admin.headers["X-CSRF-Token"]
    assert (
        admin.post(
            "/api/v1/machines", json={"name": "n", "address": "n", "ssh_user": "u"}
        ).status_code
        == 403
    )


def test_member_can_register_machine(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "member", "password": "test-password-123"},
    )
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert client.get("/api/v1/machines").status_code == 200
    assert (
        client.post(
            "/api/v1/machines", json={"name": "n", "address": "n", "ssh_user": "u"}
        ).status_code
        == 201
    )


def test_duplicate_machine_and_revision_conflict(admin):
    m = machine(admin)
    assert (
        admin.post(
            "/api/v1/machines",
            json={"name": "node1", "address": "another", "ssh_user": "u"},
        ).status_code
        == 409
    )
    url = "/api/v1/machines/" + m["id"]
    assert (
        admin.patch(url, json={"base_revision": 1, "maintenance": True}).status_code
        == 200
    )
    assert (
        admin.patch(url, json={"base_revision": 1, "maintenance": False}).status_code
        == 409
    )


def test_bad_port_and_unknown_fields(admin):
    assert (
        admin.post(
            "/api/v1/machines",
            json={"name": "a", "address": "a", "ssh_user": "a", "ssh_port": 65536},
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/v1/machines",
            json={"name": "a", "address": "a", "ssh_user": "a", "password": "secret"},
        ).status_code
        == 422
    )


def test_cluster_identity_and_reference_protection(admin):
    m, cl, e = linked(admin)
    assert cl["observed_state"] == "unknown"
    assert admin.post('/api/v1/clusters', json={"name":"bypass"}).status_code == 422
    assert (
        admin.patch(
            "/api/v1/machines/" + m["id"], json={"base_revision": 1, "archived": True}
        ).status_code
        == 409
    )
    assert (
        admin.patch(
            "/api/v1/clusters/" + cl["id"], json={"base_revision": 1, "archived": True}
        ).status_code
        == 409
    )


def test_missing_reference(admin):
    r = admin.post(
        "/api/v1/environments",
        json={
            "name": "e",
            "cluster_id": "00000000-0000-0000-0000-000000000000",
            "machine_ids": [],
        },
    )
    assert r.status_code == 422


def test_config_keeps_comments_and_advanced_fields_and_versions(admin):
    *_, e = linked(admin)
    url = "/api/v1/configs/environment/" + e["id"]
    r = admin.put(
        url + "/draft",
        json={
            "base_revision": 0,
            "mode": "yaml",
            "yaml_text": "# keep\nfilesystem: old\nadvanced:\n  flag: true\n",
        },
    )
    assert r.status_code == 200, r.text
    r = admin.put(
        url + "/draft",
        json={
            "base_revision": 1,
            "mode": "form",
            "field_updates": {"filesystem": "new"},
        },
    )
    assert r.status_code == 200, r.text
    assert "# keep" in r.json()["yaml_text"] and "flag: true" in r.json()["yaml_text"]
    assert admin.post(url + "/publish", json={"base_revision": 2}).status_code == 201
    assert (
        admin.put(
            url + "/draft",
            json={
                "base_revision": 2,
                "mode": "form",
                "field_updates": {"filesystem": "next"},
            },
        ).status_code
        == 200
    )
    assert admin.post(url + "/publish", json={"base_revision": 3}).status_code == 201
    versions = admin.get(url + "/versions").json()["items"]
    assert len(versions) == 2 and "filesystem: new" in versions[1]["yaml_text"]
    diff = admin.get(url + "/diff?from=1&to=2")
    assert "-filesystem: new" in diff.json()["diff"]
    assert (
        admin.put(
            url + "/draft",
            json={
                "base_revision": 2,
                "mode": "form",
                "field_updates": {"filesystem": "lost"},
            },
        ).status_code
        == 409
    )


def test_bad_yaml_does_not_change_saved_draft(admin):
    *_, e = linked(admin)
    url = "/api/v1/configs/environment/" + e["id"] + "/draft"
    admin.put(
        url,
        json={"base_revision": 0, "mode": "yaml", "yaml_text": "filesystem: good\n"},
    )
    for text in [
        "filesystem: [",
        "a: 1\na: 2",
        "a: &a {}\nb: *a",
        "a: !unsafe foo",
        "---\na: 1\n---\nb: 2",
        "x: " + ("a" * 1048576),
    ]:
        r = admin.put(url, json={"base_revision": 1, "mode": "yaml", "yaml_text": text})
        assert r.status_code == 422, r.text
        assert admin.get(url).json()["yaml_text"] == "filesystem: good\n"


def test_secret_never_reflected_and_unknown_form_field_rejected(admin):
    *_, e = linked(admin)
    url = "/api/v1/configs/environment/" + e["id"] + "/draft"
    secret = "never-show-this-secret"
    r = admin.put(
        url,
        json={"base_revision": 0, "mode": "yaml", "yaml_text": "password: " + secret},
    )
    assert r.status_code == 422 and secret not in r.text
    assert (
        admin.put(
            url,
            json={
                "base_revision": 0,
                "mode": "form",
                "field_updates": {"unapproved": "x"},
            },
        ).status_code
        == 422
    )


def test_cluster_yaml_is_not_marked_deployable(admin):
    _, cl, _ = linked(admin)
    url = "/api/v1/configs/cluster/" + cl["id"]
    r = admin.put(
        url + "/draft",
        json={
            "base_revision": 0,
            "mode": "yaml",
            "yaml_text": "global:\n  custom: true\n",
        },
    )
    assert r.status_code == 200
    assert r.json()["validation"]["tool_validated"] is False
    assert (
        admin.put(
            url + "/draft",
            json={
                "base_revision": 1,
                "mode": "form",
                "field_updates": {"filesystem": "bad"},
            },
        ).status_code
        == 422
    )


def test_expired_and_disabled_sessions_rejected(admin, app):
    from dingofs_platform.auth.models import User, Session
    from datetime import datetime, timezone, timedelta

    with app.state.session_factory.begin() as db:
        db.execute(
            update(Session).values(
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
    assert admin.get("/api/v1/auth/me").status_code == 401
    r = admin.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password-123"},
    )
    assert r.status_code == 200
    with app.state.session_factory.begin() as db:
        db.execute(update(User).where(User.username == "admin").values(disabled=True))
    assert admin.get("/api/v1/auth/me").status_code == 401


def test_list_search_total_and_page(admin):
    machine(admin, "alpha")
    machine(admin, "beta")
    r = admin.get("/api/v1/machines?q=alpha&limit=1").json()
    assert r["total"] == 1 and r["items"][0]["name"] == "alpha"
    assert admin.get("/api/v1/machines?limit=1&offset=1").json()["total"] == 2


def test_archive_restore_checks_parent_and_audit_has_no_values(admin, app):
    from dingofs_platform.audit.models import AuditEvent

    m, cl, e = linked(admin)
    for kind, row in [
        ("environments", e),
        ("clusters", cl),
        ("machines", m),
    ]:
        assert (
            admin.patch(
                f"/api/v1/{kind}/{row['id']}",
                json={"base_revision": 1, "archived": True},
            ).status_code
            == 200
        )
    assert (
        admin.patch(
            "/api/v1/environments/" + e["id"],
            json={"base_revision": 2, "archived": False},
        ).status_code
        == 422
    )
    with app.state.session_factory() as db:
        events = list(db.scalars(select(AuditEvent)))
        assert events and all(set(event.detail) == {"fields"} for event in events)


def test_secret_values_and_embedded_credentials_rejected(admin):
    *_, e = linked(admin)
    url = "/api/v1/configs/environment/" + e["id"] + "/draft"
    for value in [
        "rados.key: sensitive-value",
        "connection: postgres://user:secret@host/db",
        'flags: "--password=secret"',
    ]:
        r = admin.put(
            url, json={"base_revision": 0, "mode": "yaml", "yaml_text": value}
        )
        assert r.status_code == 422 and "sensitive-value" not in r.text


def test_draft_metadata_form_values_and_safe_error_location(admin):
    *_, e = linked(admin)
    url = "/api/v1/configs/environment/" + e["id"] + "/draft"
    result = admin.put(
        url,
        json={"base_revision": 0, "mode": "yaml", "yaml_text": "filesystem: example\n"},
    ).json()
    assert result["document_kind"] == "platform-environment"
    assert result["form_values"] == {"filesystem": "example"}
    bad = admin.put(
        url, json={"base_revision": 1, "mode": "yaml", "yaml_text": "filesystem: ["}
    )
    assert bad.json()["details"]["line"] >= 1


def test_concurrent_revision_updates_have_one_winner(admin, app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient

    m = machine(admin)
    barrier = Barrier(2)
    cookie = admin.cookies.get("session")
    csrf = admin.headers["X-CSRF-Token"]

    def edit(value):
        with TestClient(app) as c:
            c.cookies.set("session", cookie)
            c.headers["X-CSRF-Token"] = csrf
            barrier.wait()
            return c.patch(
                "/api/v1/machines/" + m["id"],
                json={"base_revision": 1, "maintenance": value},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, [True, False])) == [200, 409]
