from fastapi.testclient import TestClient
from dingofs_platform.auth.service import create_user
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
from test_cluster_discovery import transport


def member_client(app, name):
    with app.state.session_factory() as db:
        create_user(
            db, name, "test-password-123", "member", email=name + "@example.com"
        )
    c = TestClient(app)
    r = c.post(
        "/api/v1/auth/login", json={"username": name, "password": "test-password-123"}
    )
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def test_members_create_and_only_manage_own_machine(app, admin):
    from cryptography.fernet import Fernet

    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    with member_client(app, "alice") as a, member_client(app, "bob") as b:
        response = a.post(
            "/api/v1/machines",
            json={
                "name": "owned",
                "address": "owned.test",
                "ssh_user": "tester",
                "ssh_password": "test-secret",
            },
        )
        assert response.status_code == 201, response.text
        row = response.json()
        url = "/api/v1/machines/" + row["id"]
        assert row["creator_id"]
        assert b.get(url).status_code == 200
        assert b.get("/api/v1/machines").json()["total"] == 1
        for endpoint, payload in [
            ("", {"base_revision": 1, "name": "stolen"}),
            ("/refresh-hardware", {"base_revision": 1}),
            ("/trust-host-key", {"base_revision": 1, "challenge_id": "bad"}),
        ]:
            r = (
                b.patch(url, json=payload)
                if not endpoint
                else b.post(url + endpoint, json=payload)
            )
            assert r.status_code == 403, r.text
        assert (
            a.patch(url, json={"base_revision": 1, "name": "renamed"}).status_code
            == 200
        )
        assert (
            admin.patch(
                url, json={"base_revision": 2, "name": "admin-edit"}
            ).status_code
            == 200
        )
        assert (
            a.patch(url, json={"base_revision": 3, "creator_id": "fake"}).status_code
            == 422
        )
        assert a.post("/api/v1/environments", json={}).status_code == 403


def test_member_cluster_owner_permissions(app, admin):
    app.state.cluster_transport = transport
    with member_client(app, "alice") as a, member_client(app, "bob") as b:
        m = a.post(
            "/api/v1/machines",
            json={"name": "node", "address": "node.test", "ssh_user": "root"},
        ).json()
        from cryptography.fernet import Fernet

        app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
        a.patch(
            "/api/v1/machines/" + m["id"],
            json={"base_revision": 1, "ssh_password": "secret"},
        )
        request = {"machine_id": m["id"], "machine_revision": 2, "target_user": "root"}
        assert b.post("/api/v1/cluster-discoveries", json=request).status_code == 403
        op = a.post("/api/v1/cluster-discoveries", json=request)
        assert op.status_code == 202, op.text
        result = a.post(
            "/api/v1/cluster-discoveries/" + op.json()["id"] + "/import",
            json={"names": ["main-dingofs"]},
        )
        assert result.status_code == 200, result.text
        cid = result.json()["created"][0]["id"]
        url = "/api/v1/clusters/" + cid
        data = b.get(url).json()
        assert data["creator_id"] == m["creator_id"]
        assert b.get("/api/v1/clusters/overview").json()["total"] == 1
        assert (
            b.patch(url, json={"base_revision": 1, "name": "takeover"}).status_code
            == 403
        )
        for endpoint in ["/refresh-status", "/topology"]:
            assert b.post(url + endpoint, json={"base_revision": 1}).status_code == 403
            assert a.post(url + endpoint, json={"base_revision": 1}).status_code == 202
        assert (
            b.post(
                url + "/rebind",
                json={
                    "base_revision": 1,
                    "discovery_id": op.json()["id"],
                    "name": "main-dingofs",
                },
            ).status_code
            == 403
        )
        assert (
            a.patch(url, json={"base_revision": 1, "name": "mine"}).status_code == 200
        )
        assert (
            admin.patch(url, json={"base_revision": 2, "name": "admin"}).status_code
            == 200
        )


def test_legacy_resources_and_deleted_creator_are_not_claimed(app, admin):
    from dingofs_platform.inventory.models import Machine

    with member_client(app, "alice") as a:
        m = admin.post(
            "/api/v1/machines",
            json={"name": "legacy", "address": "legacy.test", "ssh_user": "root"},
        ).json()
        with app.state.session_factory() as db, db.begin():
            db.get(Machine, m["id"]).creator_id = None
        assert a.get("/api/v1/machines/" + m["id"]).json()["creator_id"] is None
        assert (
            a.patch(
                "/api/v1/machines/" + m["id"],
                json={"base_revision": 1, "maintenance": True},
            ).status_code
            == 403
        )
        assert (
            admin.patch(
                "/api/v1/machines/" + m["id"],
                json={"base_revision": 1, "maintenance": True},
            ).status_code
            == 200
        )


def test_config_read_shared_but_writes_and_topology_refresh_owned(app, admin):
    from cryptography.fernet import Fernet

    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    app.state.cluster_transport = transport
    with member_client(app, "alice") as a, member_client(app, "bob") as b:
        m = a.post(
            "/api/v1/machines",
            json={
                "name": "cfg",
                "address": "cfg.test",
                "ssh_user": "root",
                "ssh_password": "secret",
            },
        ).json()
        op = a.post(
            "/api/v1/cluster-discoveries",
            json={"machine_id": m["id"], "machine_revision": 1, "target_user": "root"},
        ).json()
        cid = a.post(
            "/api/v1/cluster-discoveries/" + op["id"] + "/import",
            json={"names": ["main-dingofs"]},
        ).json()["created"][0]["id"]
        url = "/api/v1/configs/cluster/" + cid
        data = {"base_revision": 0, "mode": "yaml", "yaml_text": "global: {}\n"}
        assert b.get(url + "/draft").status_code == 200
        assert b.put(url + "/draft", json=data).status_code == 403
        assert a.put(url + "/draft", json=data).status_code == 200
        assert b.post(url + "/publish", json={"base_revision": 1}).status_code == 403

        def topology(config, cmd, **kw):
            return ClusterCommandResult(
                ExecutionIdentity(cmd.target_user, "/home/root", "/bin/dingo"),
                "global: {}\n",
                "",
                0,
            )

        app.state.cluster_transport = topology
        assert (
            a.post(
                "/api/v1/clusters/" + cid + "/topology", json={"base_revision": 1}
            ).status_code
            == 202
        )
        saved = b.get("/api/v1/clusters/" + cid + "/topology")
        assert saved.status_code == 200
        assert saved.json()["stdout"] == "global: {}\n"


def test_owner_can_collect_hardware(app):
    from cryptography.fernet import Fernet
    from dingofs_platform.inventory.ssh_transport import CommandResult

    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    app.state.hardware_transport = lambda *a, **kw: {
        "memory": CommandResult("MemTotal: 1024 kB", "", 0)
    }
    with member_client(app, "alice") as a:
        m = a.post(
            "/api/v1/machines",
            json={
                "name": "hw",
                "address": "hw.test",
                "ssh_user": "root",
                "ssh_password": "secret",
            },
        ).json()
        r = a.post(
            "/api/v1/machines/" + m["id"] + "/refresh-hardware",
            json={"base_revision": 1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["last_attempt_info"]["memory"]["total_bytes"] == 1048576
