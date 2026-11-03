from dingofs_platform.cache_profiles.catalog import member_defaults
from dingofs_platform.resources import commands
from dingofs_platform.resources.remote_helper import cache_argv
import pytest

def member(weight=None):
    value = dict(machine_id="m", target_user="user", listen_ip="10.0.0.1", cache_dir="/cache", port_mode="auto")
    if weight is not None:
        value["group_weight"] = weight
    return value

def test_weights_are_preserved_and_template_weight_is_a_member_default():
    result = commands.validate("cache.plan", {"group_name": "test", "members": [member(50), member(200)]})
    assert [m["group_weight"] for m in result["members"]] == [50, 200]
    assert member_defaults({"group_weight": "250"})["group_weight"] == 250

@pytest.mark.parametrize("value", [-1, 4294967296])
def test_invalid_member_weight_rejected(value):
    with pytest.raises(ValueError):
        commands.validate("cache.plan", {"group_name": "test", "members": [member(value)]})

def test_weight_sent_once_and_old_records_keep_their_option():
    base = dict(member_id="node", group_name="g", listen_ip="127.0.0.1", listen_port=21000,
                cache_dir="/cache", cache_size_mb=1024, log_dir="/logs", cache_options={})
    for weight in [0, 100, 200]:
        argv = cache_argv({"record": {**base, "group_weight": weight}, "mds_addr": "127.0.0.1:6900"})
        assert [arg for arg in argv if arg.startswith("--group_weight=")] == ["--group_weight=" + str(weight)]
    argv = cache_argv({"record": {**base, "cache_options": {"group_weight": "73"}}, "mds_addr": "127.0.0.1:6900"})
    assert "--group_weight=73" in argv


from conftest import linked
from test_resource_api import port_runner, runner
from test_cache_profiles import add, start
from dingofs_platform.resources.models import ResourceOperation
from uuid import uuid4

def test_member_weights_override_template_and_survive_plan_consumption(admin, app, port_runner):
    machine, cluster, _ = linked(admin)
    template = add(admin, parameters={"group_weight": "250"})
    members = [{**member(weight), "machine_id": machine["id"], "target_user": "test"} for weight in (50, 200, None)]
    response = start(admin, cluster, template, {"members": members})
    assert response.status_code == 202, response.text
    oid = response.json()["id"]
    with app.state.session_factory() as db:
        operation = db.get(ResourceOperation, oid)
        assert operation.state == "succeeded", operation.result
        records = [step["record"] for step in operation.steps]
        assert [r["group_weight"] for r in records] == [50, 200, 250]
        assert all("group_weight" not in r["cache_options"] for r in records)
    response = admin.post("/api/v1/clusters/" + cluster["id"] + "/resource-operations", json={
        "action": "cache.create", "base_revision": cluster["revision"], "request_id": str(uuid4()), "confirmed": True,
        "parameters": {"plan_id": oid}})
    assert response.status_code == 202, response.text
    assert [r["record"]["group_weight"] for r in port_runner[-3:]] == [50, 200, 250]
