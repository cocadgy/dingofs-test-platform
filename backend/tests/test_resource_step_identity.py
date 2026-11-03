from copy import deepcopy
from types import SimpleNamespace
from test_resource_views import operation
from dingofs_platform.resources.views import operation_view

class Machines:
    def get(self, model, mid):
        return {"a": SimpleNamespace(name="126",address="172.30.14.126"),
                "b": SimpleNamespace(name="127",address="172.30.14.127")}.get(mid)

def test_each_result_uses_its_own_machine_and_user_without_mutating_history():
    op = operation(cursor=1, steps=[
        {"machine_id":"a","target_user":"alice"},
        {"machine_id":"b","target_user":"bob"}],
        result={"steps":[{"machine_id":"a","target_user":"alice","returncode":0},
                         {"machine_id":"b","target_user":"bob","returncode":1}]})
    original = deepcopy(op.result)
    rows = operation_view(Machines(),op)["result"]["steps"]
    assert [(r["machine_name"],r["machine_address"],r["target_user"]) for r in rows] == [
        ("126","172.30.14.126","alice"), ("127","172.30.14.127","bob")]
    assert op.result == original

def test_execution_snapshot_survives_machine_rename_and_old_result_without_identity():
    op = operation(steps=[{"machine_id":"a","machine_name":"old-126","machine_address":"10.0.0.126","target_user":"alice"}],
        result={"steps":[{"returncode":0}]})
    row = operation_view(Machines(),op)["result"]["steps"][0]
    assert (row["machine_name"],row["machine_address"],row["target_user"]) == ("old-126","10.0.0.126","alice")

def test_unknown_extra_result_does_not_borrow_current_step_identity():
    op = operation(steps=[],result={"steps":[{"returncode":1}]})
    row = operation_view(Machines(),op)["result"]["steps"][0]
    assert row.get("machine_name") is None
    assert row.get("machine_address") is None
    assert row.get("target_user") is None
