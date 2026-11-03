from uuid import uuid4
from conftest import linked
from test_resource_api import port_runner, runner
from test_cache_profiles import add
from dingofs_platform.resources.models import ResourceOperation

def start(admin, cluster, members, **options):
    return admin.post("/api/v1/clusters/"+cluster["id"]+"/resource-operations", json={
        "action":"cache.plan", "base_revision":cluster["revision"], "request_id":str(uuid4()), "confirmed":True,
        "parameters":{"group_name":"independent", "members":members, **options}})

def member(machine, **values):
    return {"machine_id":machine["id"],"target_user":"test","listen_ip":"10.0.0.1","port_mode":"auto","cache_dir":"/cache", **values}

def test_independent_options_and_template_snapshots_survive_create(admin, app, port_runner):
    machine, cluster, _ = linked(admin)
    template = add(admin, parameters={"shards":"8","cache_expire_s":"300","group_weight":"70"})
    response = start(admin, cluster, [
        member(machine, cache_options={"shards":"2","cache_expire_s":"0"}),
        member(machine, cache_profile_id=template["id"], cache_profile_revision=template["revision"]),
        member(machine, cache_profile_id=template["id"], cache_profile_revision=template["revision"], cache_options={}),
    ], cache_options={"shards":"99"})
    assert response.status_code == 202, response.text
    oid = response.json()["id"]
    with app.state.session_factory() as db:
        operation = db.get(ResourceOperation, oid)
        assert operation.state == "succeeded", operation.result
        records = [step["record"] for step in operation.steps]
        assert [r["cache_options"] for r in records] == [
            {"shards":"2","cache_expire_s":"0"}, {"shards":"8","cache_expire_s":"300"}, {}]
        assert [r["cache_expire_s"] for r in records] == [0,300,259200]
        assert [r["group_weight"] for r in records] == [100,70,100]
    result = admin.post("/api/v1/clusters/"+cluster["id"]+"/resource-operations", json={
        "action":"cache.create","base_revision":cluster["revision"],"request_id":str(uuid4()),"confirmed":True,"parameters":{"plan_id":oid}})
    assert result.status_code == 202, result.text
    assert [r["record"]["cache_options"] for r in port_runner[-3:]] == [r["cache_options"] for r in records]

def test_stale_per_machine_template_rejected_before_remote_work(admin, port_runner):
    machine, cluster, _ = linked(admin)
    template = add(admin)
    response = start(admin, cluster, [member(machine, cache_profile_id=template["id"], cache_profile_revision=99, cache_options={})])
    assert response.status_code == 409, response.text
    assert not port_runner

def test_member_template_requires_revision_pair():
    import pytest
    from dingofs_platform.resources.schemas import validate
    for extra in ({"cache_profile_revision": 1}, {"cache_profile_id": "missing"}):
        with pytest.raises(ValueError, match="cache_profile"):
            validate("cache.plan", {"group_name": "g", "members": [
                member({"id": "machine"}, **extra)
            ]})
