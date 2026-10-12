from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from dingofs_platform.inventory.models import Machine
from dingofs_platform.resources.views import MESSAGES, operation_view


OUTPUT_LIMIT_MESSAGE = "命令输出超过平台大小限制，结果未能完整返回"


class FakeDB:
    def get(self, model, object_id):
        assert model is Machine
        assert object_id == "machine-1"
        return SimpleNamespace(name="node-1")


def operation(**overrides):
    timestamp = datetime(2026, 10, 9, tzinfo=timezone.utc)
    values = dict(
        id="operation-1",
        actor_id="actor-1",
        action="fs.list",
        state="failed",
        parameters={},
        steps=[{"machine_id": "machine-1", "target_user": "dingofs"}],
        cursor=0,
        error_code="query_failed",
        resource_id=None,
        created_at=timestamp,
        expires_at=timestamp,
        result={"steps": [{"remote_state": "failed", "returncode": 1,
                           "message": "无法连接元数据服务"}]},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_query_failure_shows_failed_step_detail_and_preserves_metadata():
    view = operation_view(FakeDB(), operation())

    assert view["message"] == "无法连接元数据服务"
    assert view["error_code"] == "query_failed"
    assert view["machine_name"] == "node-1"
    assert view["target_user"] == "dingofs"
    assert view["completed_steps"] == 0
    assert view["total_steps"] == 1


def test_failure_after_completed_step_retains_partial_success_hint():
    op = operation(cursor=1)
    op.steps *= 2
    op.result["steps"].insert(0, {
        "remote_state": "succeeded", "returncode": 0,
        "message": "前置步骤成功",
    })

    view = operation_view(FakeDB(), op)

    assert view["message"].startswith("无法连接元数据服务")
    assert "部分步骤可能已经成功" in view["message"]
    assert "前置步骤成功" not in view["message"]


@pytest.mark.parametrize("error_code,detail", [
    ("query_failed", "command output exceeded limit"),
    ("query_failed", "  command output exceeded limit\n"),
    ("output_limit", None),
])
def test_output_limit_has_clear_chinese_message(error_code, detail):
    op = operation(error_code=error_code, result={"steps": [{"message": detail}]})

    assert operation_view(FakeDB(), op)["message"] == OUTPUT_LIMIT_MESSAGE


@pytest.mark.parametrize("result", [
    None,
    "invalid stored result",
    [],
    {},
    {"steps": None},
    {"steps": {}},
    {"steps": []},
    {"steps": [None]},
    {"steps": ["invalid step"]},
    {"steps": [{"message": None}]},
    {"steps": [{"message": " \n "}]},
    {"steps": [{"message": 42}]},
    {"steps": [{"message": {"sk": "example-secret"}}]},
])
def test_missing_or_malformed_failure_detail_uses_existing_fallback(result):
    view = operation_view(FakeDB(), operation(result=result))

    assert view["message"] == MESSAGES["query_failed"]


def test_missing_failed_step_does_not_reuse_previous_success_message():
    op = operation(cursor=1, result={"steps": [{
        "remote_state": "succeeded", "returncode": 0,
        "message": "前置步骤成功",
    }]})
    op.steps *= 2

    assert operation_view(FakeDB(), op)["message"] == MESSAGES["query_failed"]


@pytest.mark.parametrize("action", ["fs.list", "fs.get"])
@pytest.mark.parametrize("detail", [
    'request rejected: s3_info { ak: "example-access" sk: "example-secret" }',
    'request rejected: --s3.ak example-access --s3.sk example-secret',
    '{"error": "request rejected", "ak": "example-access", "sk": "example-secret"}',
])
def test_failure_detail_is_redacted_even_for_filesystem_get(action, detail):
    result = {"steps": [{
        "remote_state": "failed", "returncode": 1, "message": detail,
        "data": {"s3_info": {"ak": "example-access", "sk": "example-secret"}},
    }]}
    original = deepcopy(result)

    view = operation_view(FakeDB(), operation(action=action, result=result))

    assert "request rejected" in view["message"]
    assert "[REDACTED]" in view["message"]
    assert "example-access" not in view["message"]
    assert "example-secret" not in view["message"]
    expected_key = "example-secret" if action == "fs.get" else "[REDACTED]"
    assert view["result"]["steps"][0]["data"]["s3_info"]["sk"] == expected_key
    assert result == original


def test_batch_failure_keeps_existing_aggregate_message():
    op = operation(action="fs.delete_batch", error_code="batch_failed")

    assert operation_view(FakeDB(), op)["message"] == MESSAGES["batch_failed"]
