import pytest
from dingofs_platform.clusters.transport import (
    ClusterCommand,
    build_command,
    ClusterCommandResult,
    ExecutionIdentity,
)
from test_cluster_discovery import setup_machine, discover, transport


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
@pytest.mark.parametrize(
    "scope,target,flag",
    [
        ("all", None, ""),
        ("service", "5dac8acf3361", " --id 5dac8acf3361"),
        ("role", "mds", " --role mds"),
    ],
)
def test_control_command(action, scope, target, flag):
    command = ClusterCommand(action, "root", "main-dingofs", scope=scope, target=target)
    value = build_command(command, "root", "nonce", False)
    assert (
        f"export dingo_cluster=main-dingofs; dingo cluster {action}{flag} --force"
        in value
    )


def cluster(admin, app):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    cid = admin.post(
        "/api/v1/cluster-discoveries/" + op["id"] + "/import",
        json={"names": ["main-dingofs"]},
    ).json()["created"][0]["id"]
    return "/api/v1/clusters/" + cid


def test_control_requires_confirmation_and_valid_target(admin, app):
    url = cluster(admin, app)
    calls = []

    def execute(config, cmd, **kw):
        calls.append(cmd)
        return ClusterCommandResult(
            ExecutionIdentity("root", "/home/root", "/bin/dingo"), "Stopped\n", "", 0
        )

    app.state.cluster_transport = execute
    data = {
        "base_revision": 1,
        "action": "stop",
        "scope": "role",
        "target": "mds",
        "confirmed": True,
    }
    assert (
        admin.post(url + "/control", json={**data, "confirmed": False}).status_code
        == 422
    )
    assert (
        admin.post(url + "/control", json={**data, "target": "other"}).status_code
        == 422
    )
    assert (
        admin.post(
            url + "/control", json={**data, "scope": "service", "target": "other"}
        ).status_code
        == 422
    )
    assert not calls
    r = admin.post(url + "/control", json=data)
    assert r.status_code == 202, r.text
    op = admin.get("/api/v1/cluster-operations/" + r.json()["id"]).json()
    assert op["state"] == "succeeded", op
    assert len(calls) == 1 and calls[0].kind == "stop" and calls[0].target == "mds"
    assert admin.get(url).json()["status_snapshot"]["service_count"] == 10
    assert op["parameters"] == {"scope": "role", "target": "mds"}
    assert op["result"]["executed_commands"][0]["command"] == "export dingo_cluster=main-dingofs; dingo cluster stop --role mds --force"


def test_control_other_member_forbidden(admin, app):
    from test_asset_permissions import member_client

    url = cluster(admin, app)
    with member_client(app, "other") as member:
        r = member.post(
            url + "/control",
            json={
                "base_revision": 1,
                "action": "restart",
                "scope": "all",
                "confirmed": True,
            },
        )
        assert r.status_code == 403, r.text


def test_pending_control_cannot_overlap_other_targets_or_queries(admin, app):
    from dingofs_platform.clusters.transport import AuthenticationRequired

    url = cluster(admin, app)
    executed = []

    def auth(config, cmd, **kw):
        if kw.get("password") != "sudo-secret":
            raise AuthenticationRequired("test")
        executed.append(cmd)
        return ClusterCommandResult(
            ExecutionIdentity("root", "/home/root", "/bin/dingo"), "ok", "", 0
        )

    app.state.cluster_transport = auth
    payload = {
        "base_revision": 1,
        "action": "stop",
        "scope": "role",
        "target": "mds",
        "confirmed": True,
    }
    first = admin.post(url + "/control", json=payload).json()
    first = admin.get("/api/v1/cluster-operations/" + first["id"]).json()
    assert first["state"] == "needs_password" and not executed
    assert admin.post(url + "/control", json=payload).json()["id"] == first["id"]
    assert (
        admin.post(url + "/control", json={**payload, "action": "restart"}).status_code
        == 409
    )
    assert (
        admin.post(url + "/refresh-status", json={"base_revision": 1}).status_code
        == 409
    )
    answer = admin.post(
        "/api/v1/cluster-operations/" + first["id"] + "/authenticate",
        json={"challenge": first["challenge"], "password": "sudo-secret"},
    )
    assert answer.json()["state"] == "succeeded", answer.text
    assert len(executed) == 1


def test_timed_out_control_is_not_retried_by_polling(admin, app):
    from dingofs_platform.clusters.transport import ClusterExecutionError

    url = cluster(admin, app)
    calls = []

    def timeout(config, cmd, **kw):
        calls.append(cmd)
        assert kw["timeout_s"] == 300
        raise ClusterExecutionError("timeout")

    app.state.cluster_transport = timeout
    op = admin.post(
        url + "/control",
        json={
            "base_revision": 1,
            "action": "restart",
            "scope": "all",
            "confirmed": True,
        },
    ).json()
    for _ in range(3):
        result = admin.get("/api/v1/cluster-operations/" + op["id"]).json()
        assert result["state"] == "failed" and result["error_code"] == "timeout"
    assert len(calls) == 1


def test_control_rejects_shell_targets_and_checks_home_before_action():
    for target in ["mds;touch /tmp/x", "--all", "$(id)"]:
        with pytest.raises(ValueError):
            ClusterCommand("stop", "root", "main-dingofs", scope="role", target=target)
    value = build_command(
        ClusterCommand(
            "stop", "root", "main-dingofs", scope="all", expected_home="/home/root"
        ),
        "root",
        "nonce",
        False,
    )
    assert value.index('test "$HOME"') < value.index("dingo cluster stop")


def test_member_can_control_own_cluster(admin, app):
    from test_asset_permissions import member_client

    with member_client(app, "owner") as owner:
        url = cluster(owner, app)
        app.state.cluster_transport = lambda config, cmd, **kw: ClusterCommandResult(
            ExecutionIdentity("root", "/home/root", "/bin/dingo"), "started", "", 0
        )
        response = owner.post(
            url + "/control",
            json={
                "base_revision": 1,
                "action": "start",
                "scope": "all",
                "confirmed": True,
            },
        )
        assert response.status_code == 202, response.text
        assert (
            owner.get("/api/v1/cluster-operations/" + response.json()["id"]).json()[
                "state"
            ]
            == "succeeded"
        )
