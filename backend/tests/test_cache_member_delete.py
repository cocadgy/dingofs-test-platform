"""Delete discovered member registrations independently of platform processes."""
import json
import shlex

import pytest

from dingofs_platform.resources import commands, remote_helper as helper, service


MEMBER = {"member_id": "external-member", "group_name": "existing-group", "ip": "10.0.0.2", "port": 9300, "state": 3}


def test_delete_catalog_selects_member_not_managed_group():
    action = next(item for item in commands.catalog() if item["action"] == "cache.delete")
    assert action["mutating"] is True
    assert [field["key"] for field in action["fields"]] == ["member_id"]


def request(member_id="external-member"):
    script = commands.build_script("cache.delete", {"member_id": member_id}, "mds:6900", "operation-1")
    parts = shlex.split(script)
    assert parts[:2] == ["python3", "-c"]
    compile(parts[2], "remote-helper", "exec")
    return json.loads(parts[3])


def test_discovered_member_uses_cluster_management_entry_without_a_managed_resource(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "step", lambda *args, **kwargs: calls.append((args, kwargs)) or {"action": args[3], "parameters": args[4]})
    work, resource = service.prepare(None, None, None, "cache.delete", {"member_id": "external-member"})
    assert resource is None
    assert work == [{"action": "cache.delete", "parameters": {"member_id": "external-member"}}]
    assert calls[0][1] == {}  # Default management host/user, not the member host.


@pytest.mark.parametrize("parameters", [
    {"member_id": ""}, {"member_id": "--all"}, {"member_id": "one;id"},
    {"member_id": "a b"}, {"member_id": "a\nb"},
    {"member_id": "a", "resource_id": "group"}, {"member_id": "a", "pid": 123},
])
def test_member_delete_rejects_ambiguous_or_unsafe_parameters(parameters):
    with pytest.raises(ValueError):
        commands.validate("cache.delete", parameters)


def test_old_managed_group_calls_remain_valid_and_require_owned_record():
    assert commands.validate("cache.delete", {"resource_id": "saved-group"}) == {"resource_id": "saved-group"}
    with pytest.raises(ValueError, match="server-owned"):
        commands.build_script("cache.delete", {"resource_id": "saved-group"}, "mds:6900", "saved-group")


@pytest.mark.parametrize("state", [0, 3, "0", "3", "CacheGroupMemberStateUnknown", "CacheGroupMemberStateOffline"])
def test_offline_discovered_member_is_deleted_without_touching_its_process(monkeypatch, capsys, state):
    req = request()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[2:4] == ["member", "list"]:
            return {"result": {"members": [dict(MEMBER, state=state)]}}
        assert argv == ["dingo", "cache", "member", "delete", "external-member", "--mdsaddr", "mds:6900", "--noconfirm", "--format", "json"]
        return {"error": {"code": 0}, "result": {}}
    monkeypatch.setattr(helper, "run_command", run)
    monkeypatch.setattr(helper, "lifecycle", lambda req: pytest.fail("must not open process state or stop a daemon"))
    assert helper.main(req) == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["data"]["member_id"] == MEMBER["member_id"]
    assert reply["data"]["group_name"] == MEMBER["group_name"]
    assert len(calls) == 2
    assert calls[0][2:4] == ["member", "list"]


@pytest.mark.parametrize("members,reason", [
    ([], "不存在"),
    ([MEMBER, MEMBER], "重复"),
    ([dict(MEMBER, state=1)], "离线"),
    ([dict(MEMBER, state=2)], "离线"),
    ([dict(MEMBER, state="unexpected")], "离线"),
    ([dict(MEMBER, state=True)], "离线"),
    ([dict(MEMBER, state=None)], "离线"),
])
def test_rechecks_latest_membership_and_never_deletes_invalid_or_online_targets(monkeypatch, capsys, members, reason):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[2:4] == ["member", "list"], "delete must not execute"
        return {"result": {"members": members}}
    monkeypatch.setattr(helper, "run_command", run)
    assert helper.main(request()) == 1
    result = json.loads(capsys.readouterr().out)
    assert reason in result["message"]
    assert len(calls) == 1


def test_delete_command_error_is_not_reported_as_success(monkeypatch, capsys):
    def run(argv, **kwargs):
        if argv[2:4] == ["member", "list"]:
            return {"result": {"members": [MEMBER]}}
        raise helper.CommandFailure("MDS denied delete")
    monkeypatch.setattr(helper, "run_command", run)
    assert helper.main(request()) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["message"] == "MDS denied delete"
    assert result["command_completed"] is True


@pytest.mark.parametrize("ids", [[], ["one", "one"], [""], ["--all"], ["a;id"], ["x"] * 101, "vdbench*"])
def test_batch_ids_are_explicit_unique_and_bounded(ids):
    with pytest.raises(ValueError):
        commands.validate("cache.delete_batch", {"member_ids": ids})


def test_batch_expands_fixed_member_ids_in_order(monkeypatch):
    values = commands.validate("cache.delete_batch", {"member_ids": ["a", "b"]})
    monkeypatch.setattr(service, "step", lambda db, actor, cluster, action, p: (action, p))
    steps, resource = service.prepare(None, None, None, "cache.delete_batch", values)
    assert resource is None
    assert steps == [("cache.delete", {"member_id": "a"}), ("cache.delete", {"member_id": "b"})]


def test_online_precheck_is_a_known_failure_so_batch_can_continue(monkeypatch):
    monkeypatch.setattr(helper, "member_list", lambda req: [dict(MEMBER, state=1)])
    with pytest.raises(helper.CommandFailure, match="离线"):
        helper.delete_member_registration({"parameters": {"member_id": MEMBER["member_id"]}})
