from datetime import timedelta

import pytest
from test_cluster_control import cluster
from test_cluster_discovery import transport

from dingofs_platform.clusters import operations, routes
from dingofs_platform.clusters.models import ClusterOperation
from dingofs_platform.clusters.transport import AuthenticationRequired


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_expired_queued_control_never_executes(admin, app, monkeypatch, action):
    url = cluster(admin, app)
    calls = []

    def execute(config, command, **kwargs):
        calls.append(command.kind)
        return transport(config, command, **kwargs)

    def delayed(request, operation_id):
        with app.state.session_factory.begin() as db:
            operation = db.get(ClusterOperation, operation_id)
            operation.lease_expires_at = operations.now() - timedelta(seconds=1)
        operations.run_operation(request, operation_id)

    app.state.cluster_transport = execute
    monkeypatch.setattr(routes, "run_operation", delayed)
    response = admin.post(
        url + "/control",
        json={"base_revision": 1, "action": action, "scope": "all", "confirmed": True},
    )
    assert response.status_code == 202, response.text
    result = admin.get("/api/v1/cluster-operations/" + response.json()["id"]).json()
    assert result["state"] == "interrupted", result
    assert result["error_code"] == "interrupted"
    assert calls == []


def test_valid_authentication_can_resume_after_original_run_lease_expires(admin, app):
    url = cluster(admin, app)

    def execute(config, command, **kwargs):
        if kwargs.get("password") != "sudo-password":
            raise AuthenticationRequired("test")
        return transport(config, command, **kwargs)

    app.state.cluster_transport = execute
    response = admin.post(
        url + "/control",
        json={"base_revision": 1, "action": "stop", "scope": "all", "confirmed": True},
    )
    assert response.status_code == 202, response.text
    operation_url = "/api/v1/cluster-operations/" + response.json()["id"]
    operation = admin.get(operation_url).json()
    assert operation["state"] == "needs_password"
    with app.state.session_factory.begin() as db:
        db.get(ClusterOperation, operation["id"]).lease_expires_at = (
            operations.now() - timedelta(seconds=1)
        )
    response = admin.post(
        operation_url + "/authenticate",
        json={"challenge": operation["challenge"], "password": "sudo-password"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "succeeded", response.text
