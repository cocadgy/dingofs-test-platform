from uuid import uuid4
from conftest import linked


def test_cluster_resource_catalog_available(admin):
    _, cluster, _ = linked(admin)
    response = admin.get("/api/v1/clusters/" + cluster["id"] + "/resources")
    assert response.status_code == 200, response.text
    data = response.json()
    assert {item["action"] for item in data["catalog"]} >= {
        "fs.create",
        "cache.create",
        "mount.create",
        "quota.fs.delete",
        "trash.restore",
    }
    assert data["resources"] == []


def test_mutations_require_confirmation(admin):
    _, cluster, _ = linked(admin)
    response = admin.post(
        "/api/v1/clusters/" + cluster["id"] + "/resource-operations",
        json={
            "base_revision": cluster["revision"],
            "request_id": str(uuid4()),
            "action": "fs.delete",
            "parameters": {"fs_name": "main"},
            "confirmed": False,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_required"


import json
from datetime import timedelta
import pytest
from dingofs_platform.clusters.transport import (
    ClusterCommandResult,
    ExecutionIdentity,
    AuthenticationRequired,
)
from dingofs_platform.resources.models import ResourceOperation
from dingofs_platform.resources.views import now


@pytest.fixture
def runner(app, monkeypatch):
    from dingofs_platform.resources import commands

    calls = []
    monkeypatch.setattr(
        commands,
        "build_script",
        lambda action, params, mds, rid, record=None: json.dumps(
            {"action": action, "parameters": params, "record": record, "mds": mds}
        ),
    )

    def transport(config, cmd, **kwargs):
        calls.append(json.loads(cmd.resource_script))
        return ClusterCommandResult(
            ExecutionIdentity(
                cmd.target_user,
                cmd.expected_home or "/home/" + cmd.target_user,
                "/bin/dingo",
            ),
            json.dumps(
                {
                    "state": "succeeded",
                    "returncode": 0,
                    "data": {"result": {"fs_infos": []}},
                }
            ),
            "",
            0,
        )

    app.state.resource_transport = transport
    return calls


def begin(admin, c, action="fs.list", params=None, request_id=None):
    return admin.post(
        "/api/v1/clusters/" + c["id"] + "/resource-operations",
        json={
            "base_revision": c["revision"],
            "request_id": request_id or str(uuid4()),
            "action": action,
            "parameters": params or {},
            "confirmed": True,
        },
    )


def test_read_results_and_idempotent_requests(admin, runner):
    _, c, _ = linked(admin)
    rid = str(uuid4())
    first = begin(admin, c, request_id=rid)
    assert first.status_code == 202, first.text
    op = admin.get("/api/v1/resource-operations/" + first.json()["id"]).json()
    assert op["state"] == "succeeded", op
    replay = begin(admin, c, request_id=rid)
    assert replay.json()["id"] == first.json()["id"]
    assert len(runner) == 1
    assert runner[0]["mds"] == ",".join(c["status_snapshot"]["mds_addresses"])
    assert begin(admin, c, "fs.get", {"fs_name": "different"}, rid).status_code == 409


def test_storage_secrets_encrypted_while_auth_pending_and_removed_on_success(
    admin, app, runner
):
    _, c, _ = linked(admin)

    def challenge(config, cmd, **kwargs):
        if kwargs["password"] != "sudo-password":
            raise AuthenticationRequired("test")
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            json.dumps(
                {
                    "returncode": 0,
                    "data": {"s3Info": {"accessKey": "S3-AK", "secretKey": "S3-SK"}},
                }
            ),
            "",
            0,
        )

    app.state.resource_transport = challenge
    response = begin(
        admin,
        c,
        "fs.create",
        {
            "fs_name": "fresh",
            "storage_type": "s3",
            "s3_ak": "S3-AK",
            "s3_sk": "S3-SK",
            "s3_endpoint": "http://s3.test",
            "s3_bucketname": "test",
        },
    )
    assert response.status_code == 202, response.text
    oid = response.json()["id"]
    op = admin.get("/api/v1/resource-operations/" + oid).json()
    assert op["state"] == "needs_password", op
    assert "S3-SK" not in json.dumps(op)
    with app.state.session_factory() as db:
        stored = db.get(ResourceOperation, oid)
        assert stored.secret_ciphertext and "S3-SK" not in stored.secret_ciphertext
        assert "S3-SK" not in json.dumps(stored.steps)
    result = admin.post(
        "/api/v1/resource-operations/" + oid + "/authenticate",
        json={"challenge": op["challenge"], "password": "sudo-password"},
    )
    assert result.status_code == 200, result.text
    result = admin.get("/api/v1/resource-operations/" + oid)
    assert result.json()["state"] == "succeeded", result.text
    assert "S3-SK" not in result.text and "S3-AK" not in result.text
    with app.state.session_factory() as db:
        assert db.get(ResourceOperation, oid).secret_ciphertext is None


def test_exit_zero_product_error_is_failed(admin, app, runner):
    _, c, _ = linked(admin)
    app.state.resource_transport = lambda config, cmd, **kw: ClusterCommandResult(
        ExecutionIdentity("test", "/home/test", "/bin/dingo"),
        json.dumps({"data": {"result": {"error": {"errcode": "EINTERNAL"}}}}),
        "",
        0,
    )
    response = begin(admin, c)
    op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert op["state"] == "failed" and op["error_code"] == "query_failed"


def member(mid, port):
    return {
        "machine_id": mid,
        "target_user": "test",
        "listen_ip": "192.0.2.1",
        "listen_port": port,
        "cache_dir": "/mnt/cache/test",
    }


def test_auth_resume_does_not_repeat_completed_cache_member(admin, app, runner):
    m, c, _ = linked(admin)
    calls = []

    def transport(config, cmd, **kw):
        request = json.loads(cmd.resource_script)
        port = request["parameters"]["listen_port"]
        calls.append(port)
        if port == 21001 and kw["password"] != "pass":
            raise AuthenticationRequired("test")
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            '{"returncode":0,"state":"running","data":{}}',
            "",
            0,
        )

    app.state.resource_transport = transport
    response = begin(
        admin,
        c,
        "cache.create",
        {
            "group_name": "group-a",
            "members": [member(m["id"], 21000), member(m["id"], 21001)],
        },
    )
    assert response.status_code == 202, response.text
    oid = response.json()["id"]
    op = admin.get("/api/v1/resource-operations/" + oid).json()
    assert op["state"] == "needs_password" and op["completed_steps"] == 1
    assert begin(admin, c).status_code == 409
    result = admin.post(
        "/api/v1/resource-operations/" + oid + "/authenticate",
        json={"challenge": op["challenge"], "password": "pass"},
    )
    assert result.status_code == 200, result.text
    result = admin.get("/api/v1/resource-operations/" + oid)
    assert result.json()["state"] == "succeeded", result.text
    assert calls == [21000, 21001, 21001]
    resources = admin.get("/api/v1/clusters/" + c["id"] + "/resources").json()[
        "resources"
    ]
    assert resources[0]["state"] == "running"


def test_other_user_can_view_but_cannot_operate_or_resume(admin, app, runner):
    from test_asset_permissions import member_client

    _, c, _ = linked(admin)
    response = begin(admin, c)
    with member_client(app, "resource-reader") as reader:
        assert (
            reader.get("/api/v1/clusters/" + c["id"] + "/resources").status_code == 200
        )
        assert begin(reader, c).status_code == 403
        assert (
            reader.get(
                "/api/v1/resource-operations/" + response.json()["id"]
            ).status_code
            == 404
        )


def test_cancel_clears_encrypted_credentials(admin, app, runner):
    _, c, _ = linked(admin)

    def challenge(*args, **kw):
        raise AuthenticationRequired("test")

    app.state.resource_transport = challenge
    response = begin(admin, c)
    oid = response.json()["id"]
    assert (
        admin.post("/api/v1/resource-operations/" + oid + "/cancel").json()["state"]
        == "cancelled"
    )
    with app.state.session_factory() as db:
        assert db.get(ResourceOperation, oid).challenge_digest is None
    assert begin(admin, c).status_code == 202


def test_auth_budget_is_per_member_and_expired_jobs_clear_secrets(admin, app, runner):
    m, c, _ = linked(admin)

    def transport(config, cmd, **kw):
        if kw["password"] != "pass":
            raise AuthenticationRequired("test")
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            '{"returncode":0,"state":"running","data":{}}',
            "",
            0,
        )

    app.state.resource_transport = transport
    response = begin(
        admin,
        c,
        "cache.create",
        {
            "group_name": "four-members",
            "members": [member(m["id"], 21100 + i) for i in range(4)],
        },
    )
    oid = response.json()["id"]
    for i in range(4):
        op = admin.get("/api/v1/resource-operations/" + oid).json()
        assert op["state"] == "needs_password" and op["completed_steps"] == i, op
        response = admin.post(
            "/api/v1/resource-operations/" + oid + "/authenticate",
            json={"challenge": op["challenge"], "password": "pass"},
        )
    assert (
        admin.get("/api/v1/resource-operations/" + oid).json()["state"] == "succeeded"
    )
    response = begin(admin, c)
    oid = response.json()["id"]
    with app.state.session_factory.begin() as db:
        op = db.get(ResourceOperation, oid)
        op.expires_at = now() - timedelta(seconds=1)
        op.secret_ciphertext = "should-be-cleared"
    assert (
        admin.get("/api/v1/resource-operations/" + oid).json()["state"] == "interrupted"
    )
    with app.state.session_factory() as db:
        assert db.get(ResourceOperation, oid).secret_ciphertext is None


def test_pre_cancelled_transport_does_not_spawn_worker(monkeypatch):
    from unittest.mock import MagicMock
    import dingofs_platform.clusters.transport as transport

    context = MagicMock()
    context.Pipe.return_value = (MagicMock(), MagicMock())
    monkeypatch.setattr(transport.multiprocessing, "get_context", lambda mode: context)
    with pytest.raises(transport.ClusterExecutionError, match="cancelled"):
        transport.execute_cluster(None, None, cancelled=lambda: True)
    context.Process.return_value.start.assert_not_called()


def test_cluster_owner_cannot_use_another_owners_machine(admin, app, runner):
    from conftest import machine, register_cluster
    from test_asset_permissions import member_client

    foreign, _, _ = linked(admin)
    with member_client(app, "own-resource") as owner:
        own_machine = machine(owner, "own-machine")
        own_cluster = register_cluster(
            owner, own_machine, name="own-cluster", display="own"
        )
        response = begin(
            owner,
            own_cluster,
            "mount.create",
            {
                "machine_id": foreign["id"],
                "target_user": "test",
                "fs_name": "data",
                "mount_path": "/mnt/client-a",
            },
        )
        assert response.status_code == 403, response.text
        assert runner == []


def test_wrong_cluster_resource_and_stale_revision_are_rejected(admin, runner):
    m, c, _ = linked(admin)
    response = begin(admin, {**c, "revision": 999})
    assert response.status_code == 409
    response = begin(admin, c, "mount.unmount", {"resource_id": str(uuid4())})
    assert response.status_code == 422
    assert runner == []


def test_role_revocation_during_command_discards_success(admin, app, runner):
    from dingofs_platform.inventory.models import Cluster

    _, c, _ = linked(admin)

    def transport(config, cmd, **kwargs):
        with app.state.session_factory.begin() as db:
            db.get(Cluster, c["id"]).revision += 1
        return ClusterCommandResult(
            ExecutionIdentity("test", "/home/test", "/bin/dingo"),
            '{"returncode":0,"data":{}}',
            "",
            0,
        )

    app.state.resource_transport = transport
    response = begin(admin, c)
    op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert op["state"] == "interrupted" and op["error_code"] == "stale"
    assert not op["result"]["steps"]


def test_api_runs_real_read_helper_against_local_fake_cli(admin, app, tmp_path):
    import os
    import shlex
    import subprocess
    import sys

    _, c, _ = linked(admin)
    tool = tmp_path / "dingo"
    tool.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'{"error":{"code":0},"result":{"fs_infos":[{"fs_name":"helper-integration"}]}}\'\n'
    )
    tool.chmod(0o700)

    def transport(config, cmd, **kw):
        argv = shlex.split(cmd.resource_script)
        result = subprocess.run(
            [sys.executable, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        )
        return ClusterCommandResult(
            ExecutionIdentity(cmd.target_user, cmd.expected_home, "/bin/dingo"),
            result.stdout,
            result.stderr,
            result.returncode,
        )

    app.state.resource_transport = transport
    response = begin(admin, c)
    assert response.status_code == 202, response.text
    op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert op["state"] == "succeeded", op
    assert "helper-integration" in json.dumps(op["result"])


@pytest.mark.parametrize("action", ["fs.list", "fs.get"])
def test_large_list_transport_budget_does_not_change_other_operations(admin, app, runner, action):
    _, cluster, _ = linked(admin)
    payload = json.dumps({
        "state": "succeeded", "returncode": 0,
        "data": {"result": {"fs_infos": [{"fs_name": "large-list", "fs_id": 42}],
                            "info": "x" * (2 * 1024 * 1024)}},
    })
    limits = []

    def transport(config, cmd, **kwargs):
        limits.append(kwargs["max_bytes"])
        return ClusterCommandResult(
            ExecutionIdentity(cmd.target_user, cmd.expected_home, "/bin/dingo"),
            payload, "", 0,
        )

    app.state.resource_transport = transport
    response = begin(admin, cluster, action, {"fs_name": "large-list"} if action == "fs.get" else {})
    assert response.status_code == 202, response.text
    op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    if action == "fs.list":
        assert op["state"] == "succeeded", op.get("message")
        assert limits[0] >= len(payload.encode())
        assert op["result"]["steps"][0]["data"]["result"]["fs_infos"][0]["fs_id"] == 42
    else:
        assert op["state"] == "failed" and op["error_code"] == "output_limit"
        assert limits == [app.state.settings.cluster_max_bytes]


@pytest.mark.parametrize("action,parameters", [
    ("cache.delete", {"member_id": "external-member"}),
    ("cache.delete_batch", {"member_ids": ["external-member", "another-member"]}),
])
def test_discovered_cache_member_delete_is_confirmed_and_runs_on_management_entry(admin, app, runner, action, parameters):
    _, cluster, _ = linked(admin)
    url = "/api/v1/clusters/" + cluster["id"] + "/resource-operations"
    payload = {"base_revision": cluster["revision"], "request_id": str(uuid4()),
               "action": action, "parameters": parameters,
               "confirmed": False}
    response = admin.post(url, json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_required"
    assert runner == []
    payload["confirmed"] = True
    response = admin.post(url, json=payload)
    assert response.status_code == 202, response.text
    op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
    assert op["state"] == "succeeded", op
    assert op["resource_id"] is None
    assert len(runner) == (2 if action == "cache.delete_batch" else 1)
    assert runner[0]["parameters"] == {"member_id": "external-member"}
    assert runner[0]["record"] is None
    with app.state.session_factory() as db:
        saved = db.get(ResourceOperation, op["id"])
        assert saved.steps[0]["machine_id"] == cluster["management_machine_id"]
        assert saved.steps[0]["target_user"] == cluster["os_user"]
    replay = admin.post(url, json=payload)
    assert replay.json()["id"] == op["id"] and len(runner) == (2 if action == "cache.delete_batch" else 1)


def test_same_cache_group_creates_distinct_members_and_records(admin, app, runner):
    m, c, _ = linked(admin)
    ids = []
    for port in (21000, 21001):
        response = begin(admin, c, "cache.create", {"group_name": "shared-group", "members": [member(m["id"], port)]})
        assert response.status_code == 202, response.text
        op = admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()
        assert op["state"] == "succeeded", op
        ids.append(op["resource_id"])
    assert len(set(ids)) == 2
    assert len({call["parameters"]["member_id"] for call in runner}) == 2
    assert len({call["parameters"]["cache_dir"] for call in runner}) == 2
    assert all(call["parameters"]["group_name"] == "shared-group" for call in runner)


def test_duplicate_mount_directory_still_rejected(admin, runner):
    m, c, _ = linked(admin)
    params = {"machine_id": m["id"], "target_user": "test", "fs_name": "data", "mount_path": "/mnt/client-a"}
    response = begin(admin, c, "mount.create", params)
    assert response.status_code == 202, response.text
    assert admin.get("/api/v1/resource-operations/" + response.json()["id"]).json()["state"] == "succeeded"
    repeated = begin(admin, c, "mount.create", params)
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["code"] == "resource_exists"
    assert len(runner) == 1


@pytest.fixture
def port_runner(app, runner):
    def transport(config, cmd, **kw):
        req=json.loads(cmd.resource_script)
        runner.append(req)
        member=req['record']
        data={'effective_port':member['listen_port'],'member':member}
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user,cmd.expected_home or '/home/'+cmd.target_user,'/bin/dingo'),json.dumps({'state':'planned' if req['action']=='cache.plan' else 'running','returncode':0,'data':data}),'',0)
    app.state.resource_transport=transport
    return runner


def test_port_plan_allocates_distinct_ports_and_is_consumed_once(admin, app, port_runner):
    m,c,_=linked(admin)
    response=begin(admin,c,'cache.plan',{'group_name':'planned','members':[{**member(m['id'],21000),'port_mode':'auto'}]*2})
    assert response.status_code==202,response.text
    plan=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert plan['state']=='succeeded',json.dumps(plan, ensure_ascii=False)
    assert [call['record']['listen_port'] for call in port_runner]==[21000,21001]
    assert all(call['action']=='cache.plan' for call in port_runner)
    assert begin(admin,c,'cache.stop',{'resource_id':plan['resource_id']}).status_code==422
    payload={'plan_id':plan['id']}
    created=begin(admin,c,'cache.create',payload)
    assert created.status_code==202,created.text
    result=admin.get('/api/v1/resource-operations/'+created.json()['id']).json()
    assert result['state']=='succeeded',result
    assert result['resource_id']==plan['resource_id']
    assert [call['record']['member_id'] for call in port_runner[:2]]==[call['record']['member_id'] for call in port_runner[2:]]
    assert begin(admin,c,'cache.create',payload).status_code==409


def test_expired_plan_and_changed_machine_cannot_create(admin, app, port_runner):
    m,c,_=linked(admin)
    response=begin(admin,c,'cache.plan',{'group_name':'planned','members':[member(m['id'],21000)]})
    oid=response.json()['id']
    assert admin.get('/api/v1/resource-operations/'+oid).json()['state']=='succeeded'
    with app.state.session_factory.begin() as db:
        db.get(ResourceOperation,oid).created_at=now()-timedelta(minutes=11)
    assert begin(admin,c,'cache.create',{'plan_id':oid}).status_code==409
    assert len(port_runner)==1


def test_two_plans_reserve_different_ports_and_manual_conflicts_fail(admin, port_runner):
    m,c,_=linked(admin)
    for name,port in [('first',21000),('second',21001)]:
        response=begin(admin,c,'cache.plan',{'group_name':name,'members':[{**member(m['id'],21000),'port_mode':'auto'}]})
        assert response.status_code==202,response.text
        result=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
        assert result['state']=='succeeded',result
        assert port_runner[-1]['record']['listen_port']==port
    response=begin(admin,c,'cache.plan',{'group_name':'manual','members':[member(m['id'],21000)]})
    assert response.status_code==409,response.text
    assert response.json()['code']=='port_reserved'


def test_plan_bound_to_machine_revision_and_confirmed_creation(admin, app, port_runner):
    from dingofs_platform.inventory.models import Machine
    m,c,_=linked(admin)
    response=begin(admin,c,'cache.plan',{'group_name':'planned','members':[member(m['id'],21000)]})
    oid=response.json()['id']
    assert admin.get('/api/v1/resource-operations/'+oid).json()['state']=='succeeded'
    url='/api/v1/clusters/'+c['id']+'/resource-operations'
    payload={'action':'cache.create','parameters':{'plan_id':oid},'request_id':str(uuid4()),'base_revision':c['revision'],'confirmed':False}
    assert admin.post(url,json=payload).status_code==422
    with app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).revision+=1
    payload['confirmed']=True
    assert admin.post(url,json=payload).status_code==409
    assert len(port_runner)==1


def test_stop_members_spans_records_and_single_member_does_not_stop_sibling(admin, app, runner, monkeypatch):
    from dingofs_platform.resources.models import ManagedResource
    from dingofs_platform.resources import commands
    m, c, _ = linked(admin)
    for ports in ([21000, 21001], [21002]):
        response = begin(admin, c, 'cache.create', {'group_name': 'g', 'members': [member(m['id'], port) for port in ports]})
        assert response.status_code == 202, response.text
    resources = admin.get('/api/v1/clusters/'+c['id']+'/resources').json()['resources']
    a, sibling = resources[0]['data']['members']
    b = resources[1]['data']['members'][0]
    # Observe the immutable ID used by OwnedState, not the new operation UUID.
    monkeypatch.setattr(commands, 'build_script', lambda action, params, mds, rid, record=None:
        json.dumps({'action':action, 'parameters':params, 'record':record, 'resource_id':rid}))
    runner.clear()
    response = begin(admin,c,'cache.stop',{'member_ids':[a['member_id'], b['member_id']]})
    assert response.status_code == 202, response.text
    result = admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert result['state'] == 'succeeded', result
    assert [x['action'] for x in runner] == ['cache.stop','cache.stop']
    assert [x['resource_id'] for x in runner[:2]] == [resources[0]['id'],resources[1]['id']]
    assert [x['record']['member_id'] for x in runner[:2]] == [a['member_id'],b['member_id']]
    with app.state.session_factory() as db:
        first=db.get(ManagedResource,resources[0]['id'])
        assert first.state == 'partial'
        assert first.data['members'][1].get('process_state') == sibling.get('process_state')
        assert db.get(ManagedResource,resources[1]['id']).state == 'stopped'
    assert len(result['result']['steps']) == 2
    before=len(runner)
    assert begin(admin,c,'cache.stop',{'member_ids':[a['member_id'],'external']}).status_code == 422
    assert len(runner) == before


def test_stop_members_require_confirmation(admin, runner):
    _, c, _ = linked(admin)
    response=admin.post('/api/v1/clusters/'+c['id']+'/resource-operations', json={
        'base_revision':c['revision'],'request_id':str(uuid4()),'action':'cache.stop',
        'parameters':{'member_ids':['a']},'confirmed':False})
    assert response.status_code == 422
    assert response.json()['code'] == 'confirmation_required'
    assert not runner


@pytest.mark.parametrize('failure', ['known', 'unknown'])
def test_member_stop_failures_never_report_group_success(admin, app, runner, failure):
    m,c,_=linked(admin)
    response=begin(admin,c,'cache.create',{'group_name':'g','members':[member(m['id'],21000),member(m['id'],21001)]})
    assert response.status_code == 202
    resources=admin.get('/api/v1/clusters/'+c['id']+'/resources').json()['resources']
    ids=[x['member_id'] for x in resources[0]['data']['members']]
    calls=[]
    from dingofs_platform.clusters.transport import ClusterExecutionError
    def transport(config,cmd,**kwargs):
        req=json.loads(cmd.resource_script); calls.append(req)
        failed=req['action']=='cache.stop' and len(calls)==1
        if failed and failure=='unknown':
            raise ClusterExecutionError('timeout')
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'),json.dumps({
            'state':'failed' if failed else 'stopped', 'returncode':int(failed),
            'message':'test failure' if failed else None,'data':{},
        }),'',int(failed))
    app.state.resource_transport=transport
    response=begin(admin,c,'cache.stop',{'member_ids':ids})
    assert response.status_code==202,response.text
    result=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert result['state']=='failed', result
    assert len(calls)==(1 if failure=='unknown' else 2)
    if failure=='known':
        assert [s['failed'] for s in result['result']['steps'][:2]]==[True,False]


def test_discovered_external_member_stops_and_deletes_without_managed_record(admin, app, runner):
    from dingofs_platform.inventory.models import Machine
    m,c,_=linked(admin)
    with app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).hardware_info={'interfaces':[{'addresses':['192.0.2.1/24']}]}
    row={'member_id':'external','group_name':'g','ip':'192.0.2.1','port':21000,'state':1}
    calls=[]
    def transport(config,cmd,**kwargs):
        req=json.loads(cmd.resource_script);calls.append((req,cmd))
        data={'members':{'result':{'members':[dict(row)]}}} if req['action']=='cache.list' else {}
        if req['action']=='cache.stop_external':
            assert cmd.target_user=='root' and not cmd.resource_requires_dingo
            assert req['record']['member_id']=='external'
            row['state']=3
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user,cmd.expected_home or '/root','/usr/bin/python3'),json.dumps({'state':'succeeded','returncode':0,'data':data}),'',0)
    app.state.resource_transport=transport
    assert begin(admin,c,'cache.list').status_code==202
    inventory=admin.get('/api/v1/clusters/'+c['id']+'/resources').json()
    assert inventory['resources']==[]
    assert inventory['cache_member_targets']['external']['can_stop'] is True
    response=begin(admin,c,'cache.stop',{'member_ids':['external']})
    assert response.status_code==202,response.text
    result=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert result['state']=='succeeded',result
    assert [req['action'] for req,cmd in calls]==['cache.list','cache.verify_members','cache.stop_external']
    response=begin(admin,c,'cache.delete',{'member_id':'external'})
    assert response.status_code==202,response.text
    assert admin.get('/api/v1/resource-operations/'+response.json()['id']).json()['state']=='succeeded'
    assert admin.get('/api/v1/clusters/'+c['id']+'/resources').json()['resources']==[]


def test_changed_external_registration_aborts_before_any_process_stop(admin,app,runner):
    from dingofs_platform.inventory.models import Machine
    m,c,_=linked(admin)
    with app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).aliases=['192.0.2.1']
    calls=[]
    def transport(config,cmd,**kwargs):
        req=json.loads(cmd.resource_script);calls.append(req['action'])
        if req['action']=='cache.list':
            data={'members':{'result':{'members':[{'member_id':'x','group_name':'g','ip':'192.0.2.1','port':21000}]}}}
            return ClusterCommandResult(ExecutionIdentity(cmd.target_user,cmd.expected_home,'/bin/dingo'),json.dumps({'state':'succeeded','data':data}),'',0)
        assert req['action']=='cache.verify_members'
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user,cmd.expected_home,'/bin/dingo'),json.dumps({'state':'failed','message':'member changed'}),'',1)
    app.state.resource_transport=transport
    assert begin(admin,c,'cache.list').status_code==202
    response=begin(admin,c,'cache.stop',{'member_ids':['x']})
    assert response.status_code==202,response.text
    result=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert result['state']=='failed' and result['message']=='member changed'
    assert calls==['cache.list','cache.verify_members']


def test_rdma_inventory_uses_machine_hardware_pairs():
    from types import SimpleNamespace
    from dingofs_platform.resources.service import machine_rdma_ports
    machine = SimpleNamespace(hardware_info={"rdma": [{"device": "mlx5_0", "port": 1}]}, last_attempt_info=None, collection_status="success")
    assert machine_rdma_ports(machine) == [{"device": "mlx5_0", "port": 1, "interfaces": []}]
    machine.hardware_info = {"rdma": []}
    assert machine_rdma_ports(machine) == []
    machine.hardware_info = {}
    assert machine_rdma_ports(machine) is None


def test_read_only_cluster_collection_does_not_block_resource_operation(admin, app, runner):
    from datetime import timedelta
    from dingofs_platform.clusters.models import ClusterOperation
    from dingofs_platform.resources.views import now

    machine, cluster, _ = linked(admin)
    with app.state.session_factory.begin() as db:
        collecting = ClusterOperation(
            actor_id=cluster['creator_id'], session_id='test-session',
            kind='status', parameters={}, machine_id=machine['id'],
            machine_revision=machine['revision'], target_user='test',
            cluster_id=cluster['id'], cluster_revision=cluster['revision'],
            state='running', lease_token='test-lease',
            lease_expires_at=now() + timedelta(minutes=5),
            expires_at=now() + timedelta(minutes=5), auth_attempts=0,
        )
        db.add(collecting)
    assert begin(admin, cluster, 'fs.list').status_code == 202
    with app.state.session_factory.begin() as db:
        db.get(ClusterOperation, collecting.id).kind = 'topology'
    assert begin(admin, cluster, 'fs.list').status_code == 202
    with app.state.session_factory.begin() as db:
        db.get(ClusterOperation, collecting.id).kind = 'stop'
    blocked = begin(admin, cluster, 'fs.list')
    assert blocked.status_code == 409
    assert blocked.json()['code'] == 'cluster_busy'


def test_restore_uses_root_for_only_its_remote_step(admin, runner):
    from conftest import linked
    machine, cluster, _ = linked(admin)
    from dingofs_platform.resources import commands, service
    with admin.app.state.session_factory.begin() as db:
        from dingofs_platform.inventory.models import Cluster
        from dingofs_platform.auth.models import User
        c=db.get(Cluster, cluster["id"])
        actor=db.get(User, admin.get("/api/v1/auth/me").json()["id"])
        p=commands.validate("trash.restore", {"fs_id": 5})
        steps,_=service.prepare(db, actor, c, "trash.restore", p)
    assert steps[0]["target_user"] == "root"
    assert steps[0]["tool_home"] == c.execution_home
