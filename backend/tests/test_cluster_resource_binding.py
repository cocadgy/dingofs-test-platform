from dataclasses import replace

import pytest
from test_cluster_control import cluster
from test_cluster_discovery import discover, transport

from dingofs_platform.inventory.models import Cluster
from dingofs_platform.resources.models import ManagedResource


def registered_resource(admin, app, kind="mount", state="mounted"):
    url = cluster(admin, app)
    before = admin.get(url).json()
    with app.state.session_factory.begin() as db:
        row = db.get(Cluster, before["id"])
        resource = ManagedResource(
            cluster_id=row.id,
            creator_id=row.creator_id,
            kind=kind,
            name="registered-resource",
            state=state,
            data={"machine_id": row.management_machine_id, "target_user": row.os_user},
        )
        db.add(resource)
        db.flush()
        resource_id = resource.id
    return url, before, resource_id


def rebind(admin, url, before, discovery, name="main-dingofs"):
    return admin.post(
        url + "/rebind",
        json={
            "base_revision": before["revision"],
            "discovery_id": discovery["id"],
            "name": name,
        },
    )


@pytest.mark.parametrize(
    "kind,state",
    [
        ("mount", "mounted"),
        ("mount", "unmounted"),
        ("cache", "running"),
        ("cache", "deleted"),
    ],
)
def test_rebind_preserves_existing_and_historical_resource_cluster(
    admin, app, kind, state
):
    url, before, resource_id = registered_resource(admin, app, kind, state)
    machine = admin.get("/api/v1/machines/" + before["management_machine_id"]).json()
    discovery = discover(admin, machine, before["os_user"])
    response = rebind(admin, url, before, discovery, "test-dingofs")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "resource_binding_conflict"
    after = admin.get(url).json()
    assert after["external_name"] == before["external_name"]
    assert after["revision"] == before["revision"]
    with app.state.session_factory() as db:
        assert db.get(ManagedResource, resource_id).cluster_id == before["id"]


@pytest.mark.parametrize("changed", ["machine", "user", "home", "config_dir"])
def test_rebind_rejects_other_resource_binding_changes(admin, app, changed):
    url, before, _ = registered_resource(admin, app)
    machine = admin.get("/api/v1/machines/" + before["management_machine_id"]).json()
    user = before["os_user"]
    if changed == "machine":
        response = admin.post(
            "/api/v1/machines",
            json={
                "name": "other",
                "address": "other.test",
                "ssh_user": "test",
                "ssh_password": "SSH-sentinel",
            },
        )
        assert response.status_code == 201, response.text
        machine = admin.get("/api/v1/machines/" + response.json()["id"]).json()
    elif changed == "user":
        user = "other"
    elif changed == "home":

        def moved_home(config, command, **kwargs):
            output = transport(config, command, **kwargs)
            return replace(output, identity=replace(output.identity, home="/srv/root"))

        app.state.cluster_transport = moved_home
    else:
        with app.state.session_factory.begin() as db:
            db.get(Cluster, before["id"]).config_dir = "/old/config"
        before = admin.get(url).json()
    discovery = discover(admin, machine, user)
    response = rebind(admin, url, before, discovery)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "resource_binding_conflict"
    after = admin.get(url).json()
    for key in (
        "management_machine_id",
        "os_user",
        "external_name",
        "config_dir",
        "execution_home",
        "revision",
    ):
        assert after[key] == before[key]


def test_rebind_without_managed_resources_can_change_target(admin, app):
    url = cluster(admin, app)
    before = admin.get(url).json()
    machine = admin.get("/api/v1/machines/" + before["management_machine_id"]).json()
    discovery = discover(admin, machine, before["os_user"])
    response = rebind(admin, url, before, discovery, "test-dingofs")
    assert response.status_code == 200, response.text
    assert response.json()["external_name"] == "test-dingofs"


def test_rebind_same_resource_binding_can_refresh_executable(admin, app):
    url, before, _ = registered_resource(admin, app)
    machine = admin.get("/api/v1/machines/" + before["management_machine_id"]).json()

    def upgraded(config, command, **kwargs):
        output = transport(config, command, **kwargs)
        return replace(
            output, identity=replace(output.identity, dingo_path="/opt/new/dingo")
        )

    app.state.cluster_transport = upgraded
    discovery = discover(admin, machine, before["os_user"])
    response = rebind(admin, url, before, discovery)
    assert response.status_code == 200, response.text
    assert response.json()["resolved_dingo_path"] == "/opt/new/dingo"
    assert response.json()["revision"] == before["revision"] + 1
