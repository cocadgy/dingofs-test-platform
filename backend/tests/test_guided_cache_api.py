import json
from conftest import linked
from test_resource_api import runner, begin, member
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity


def test_plan_pins_binary_and_retry_only_runs_unfinished_members(admin, app, runner):
    machine, cluster, _ = linked(admin)
    info = {"path": "/opt/cache/dingo-cache", "version": "main-fe4384a", "sha256": "a" * 64}
    starts = []

    def transport(config, cmd, **kwargs):
        req = json.loads(cmd.resource_script)
        record = req["record"]
        runner.append(req)
        failed = False
        if req["action"] == "cache.plan":
            data = {"effective_port": record["listen_port"], "member": {**record, "binary_info": info}}
        else:
            assert record["binary_info"] == info
            starts.append(record["member_id"])
            failed = len(starts) == 2
            data = {"effective_port": record["listen_port"]}
        result = {"state": "failed" if failed else "planned" if req["action"] == "cache.plan" else "running",
                  "returncode": 1 if failed else 0, "message": "simulated start failure" if failed else "", "data": data}
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user, cmd.expected_home or "/home/test", "/bin/dingo"), json.dumps(result), "", 0)

    app.state.resource_transport = transport
    response = begin(admin, cluster, "cache.plan", {"group_name": "guided-cache", "members": [
        {**member(machine["id"], 21000 + i), "binary_source": "path", "binary_directory": "/opt/cache"}
        for i in range(3)]})
    assert response.status_code == 202, response.text
    plan = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert plan["state"] == "succeeded", plan
    ids = [call["record"]["member_id"] for call in runner]
    response = begin(admin, cluster, "cache.create", {"plan_id": plan["id"]})
    assert response.status_code == 202, response.text
    failed = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert failed["state"] == "failed", failed
    response = begin(admin, cluster, "cache.create", {"retry_operation_id": failed["id"]})
    assert response.status_code == 202, response.text
    retried = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert retried["state"] == "succeeded", retried
    assert retried["resource_id"] == plan["resource_id"]
    assert starts == [ids[0], ids[1], ids[1], ids[2]]
