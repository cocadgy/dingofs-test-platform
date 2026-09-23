from sqlalchemy import select
from fastapi.testclient import TestClient
from dingofs_platform.auth.models import User, Session
from dingofs_platform.auth.service import hasher


def account(admin, name="alice", role="member"):
    r = admin.post(
        "/api/v1/users",
        json={
            "username": name,
            "email": name + "@example.com",
            "password": "initial-password-123",
            "role": role,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def login(client, name="alice", password="initial-password-123"):
    r = client.post("/api/v1/auth/login", json={"username": name, "password": password})
    if r.status_code == 200:
        client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r


def test_admin_add_list_required_email_and_no_hash(admin):
    for body in [
        dict(username="a", password="initial-password-123"),
        dict(username="a", email="invalid", password="initial-password-123"),
    ]:
        assert admin.post("/api/v1/users", json=body).status_code == 422
    u = account(admin)
    assert u["email"] == "alice@example.com" and "password" not in str(u)
    listing = admin.get("/api/v1/users?q=alice").json()
    assert listing["total"] == 1 and listing["items"][0]["username"] == "alice"
    assert "password_hash" not in str(listing)


def test_disable_enable_revokes_old_sessions(admin, app):
    u = account(admin)
    with TestClient(app) as c:
        assert login(c).status_code == 200
        r = admin.patch(
            "/api/v1/users/" + u["id"],
            json={"base_revision": u["revision"], "disabled": True},
        )
        assert r.status_code == 200
        assert c.get("/api/v1/auth/me").status_code == 401
        assert login(c).status_code == 401
        assert (
            admin.patch(
                "/api/v1/users/" + u["id"],
                json={"base_revision": r.json()["revision"], "disabled": False},
            ).status_code
            == 200
        )
        assert c.get("/api/v1/auth/me").status_code == 401
        assert login(c).status_code == 200


def test_reset_password_is_exact_and_sessions_revoked(admin, app):
    u = account(admin)
    with TestClient(app) as c:
        login(c)
        assert (
            admin.post(
                "/api/v1/users/" + u["id"] + "/reset-password",
                json={"base_revision": 1},
            ).status_code
            == 200
        )
        assert c.get("/api/v1/auth/me").status_code == 401
        assert login(c).status_code == 401
        assert login(c, password="123456").status_code == 200
    with app.state.session_factory() as db:
        assert hasher.verify(db.get(User, u["id"]).password_hash, "123456")


def test_delete_user_removes_sessions_and_prevents_login(admin, app):
    u = account(admin)
    with TestClient(app) as c:
        login(c)
        assert (
            admin.delete("/api/v1/users/" + u["id"] + "?base_revision=1").status_code
            == 204
        )
        assert c.get("/api/v1/auth/me").status_code == 401
        assert login(c).status_code == 401
    with app.state.session_factory() as db:
        assert db.get(User, u["id"]) is None
        assert db.scalar(select(Session).where(Session.user_id == u["id"])) is None


def test_member_cannot_manage_users_or_escalate(admin, app):
    u = account(admin)
    with TestClient(app) as c:
        login(c)
        assert c.get("/api/v1/users").status_code == 403
        assert (
            c.post(
                "/api/v1/users",
                json={
                    "username": "evil",
                    "email": "e@example.com",
                    "password": "initial-password-123",
                    "role": "admin",
                },
            ).status_code
            == 403
        )
        assert (
            c.patch(
                "/api/v1/users/" + u["id"], json={"base_revision": 1, "disabled": True}
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/users/" + u["id"] + "/reset-password",
                json={"base_revision": 1},
            ).status_code
            == 403
        )
        assert (
            c.delete("/api/v1/users/" + u["id"] + "?base_revision=1").status_code == 403
        )
        assert (
            c.patch(
                "/api/v1/auth/profile",
                json={
                    "current_password": "initial-password-123",
                    "email": "new@example.com",
                    "role": "admin",
                },
            ).status_code
            == 422
        )


def test_self_email_and_password_require_current_password(admin, app):
    account(admin)
    with TestClient(app) as c:
        login(c)
        for body in [
            {"email": "new@example.com"},
            {"email": "new@example.com", "current_password": "wrong"},
            {"new_password": "new-password-123", "current_password": "wrong"},
        ]:
            assert c.patch("/api/v1/auth/profile", json=body).status_code in (403, 422)
        assert c.get("/api/v1/auth/me").json()["email"] == "alice@example.com"
        r = c.patch(
            "/api/v1/auth/profile",
            json={
                "email": "new@example.com",
                "current_password": "initial-password-123",
            },
        )
        assert r.status_code == 200 and r.json()["email"] == "new@example.com"
        assert (
            c.patch(
                "/api/v1/auth/profile",
                json={"email": "bad", "current_password": "initial-password-123"},
            ).status_code
            == 422
        )
        r = c.patch(
            "/api/v1/auth/profile",
            json={
                "new_password": "new-password-123",
                "current_password": "initial-password-123",
            },
        )
        assert r.status_code == 200 and r.json()["reauthenticate"] is True
        assert c.get("/api/v1/auth/me").status_code == 401
        assert login(c).status_code == 401
        assert login(c, password="new-password-123").status_code == 200


def test_last_enabled_admin_and_revision_conflict(admin):
    me = admin.get("/api/v1/auth/me").json()
    assert (
        admin.patch(
            "/api/v1/users/" + me["id"], json={"base_revision": 1, "disabled": True}
        ).status_code
        == 409
    )
    assert (
        admin.delete("/api/v1/users/" + me["id"] + "?base_revision=1").status_code
        == 409
    )
    u = account(admin)
    assert (
        admin.patch(
            "/api/v1/users/" + u["id"], json={"base_revision": 1, "disabled": True}
        ).status_code
        == 200
    )
    assert (
        admin.post(
            "/api/v1/users/" + u["id"] + "/reset-password", json={"base_revision": 1}
        ).status_code
        == 409
    )


def test_user_writes_require_csrf(admin):
    u = account(admin)
    del admin.headers["X-CSRF-Token"]
    assert (
        admin.post(
            "/api/v1/users/" + u["id"] + "/reset-password", json={"base_revision": 1}
        ).status_code
        == 403
    )
    assert (
        admin.patch(
            "/api/v1/auth/profile",
            json={"current_password": "test-password-123", "email": "new@example.com"},
        ).status_code
        == 403
    )


def test_password_change_revokes_other_browsers_and_audit_omits_secrets(admin, app):
    from dingofs_platform.audit.models import AuditEvent

    account(admin)
    with TestClient(app) as first, TestClient(app) as second:
        login(first)
        login(second)
        assert (
            first.patch(
                "/api/v1/auth/profile",
                json={
                    "current_password": "initial-password-123",
                    "new_password": "changed-password-123",
                },
            ).status_code
            == 200
        )
        assert second.get("/api/v1/auth/me").status_code == 401
    with app.state.session_factory() as db:
        details = str([(x.action, x.detail) for x in db.scalars(select(AuditEvent))])
        assert (
            "initial-password-123" not in details
            and "changed-password-123" not in details
        )


def test_concurrent_admin_disables_leave_one_active(admin, app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    account(admin, "second-admin", "admin")
    gate = Barrier(2)

    def disable(name, password):
        with TestClient(app) as c:
            r = login(c, name, password)
            assert r.status_code == 200
            id = r.json()["id"]
            gate.wait()
            return c.patch(
                "/api/v1/users/" + id, json={"base_revision": 1, "disabled": True}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(disable, "admin", "test-password-123")
        second = pool.submit(disable, "second-admin", "initial-password-123")
        assert sorted([first.result(), second.result()]) == [200, 409]
    with app.state.session_factory() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(User).where(User.role == "admin", User.disabled == False)
                    )
                )
            )
            == 1
        )
