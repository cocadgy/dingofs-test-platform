from conftest import machine, register_cluster


def test_direct_cluster_creation_and_target_edit_rejected(admin):
    m = machine(admin)
    c = register_cluster(admin, m)
    assert admin.post("/api/v1/clusters", json={"name": "bypass"}).status_code == 422
    assert (
        admin.patch(
            "/api/v1/clusters/" + c["id"], json={"base_revision": 1, "os_user": "other"}
        ).status_code
        == 422
    )
    r = admin.patch(
        "/api/v1/clusters/" + c["id"], json={"base_revision": 1, "name": "renamed"}
    )
    assert r.status_code == 200 and r.json()["name"] == "renamed"
    assert (
        admin.patch(
            "/api/v1/clusters/" + c["id"], json={"base_revision": 1, "name": "stale"}
        ).status_code
        == 409
    )


def test_management_machine_protected_without_membership(admin):
    m = machine(admin)
    c = register_cluster(admin, m)
    assert (
        admin.patch(
            "/api/v1/machines/" + m["id"], json={"base_revision": 1, "archived": True}
        ).status_code
        == 409
    )
    assert (
        admin.patch(
            "/api/v1/clusters/" + c["id"], json={"base_revision": 1, "archived": True}
        ).status_code
        == 200
    )
    assert (
        admin.patch(
            "/api/v1/machines/" + m["id"], json={"base_revision": 1, "archived": True}
        ).status_code
        == 200
    )
    assert (
        admin.patch(
            "/api/v1/clusters/" + c["id"], json={"base_revision": 2, "archived": False}
        ).status_code
        == 422
    )


def test_context_endpoints_removed(admin):
    assert admin.get("/api/v1/management-contexts").status_code == 404
    assert admin.post("/api/v1/management-contexts", json={}).status_code == 404
