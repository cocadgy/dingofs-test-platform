import pytest
from dingofs_platform.resources.safety import redact


@pytest.mark.parametrize(
    "text",
    [
        's3_info { ak: "EXAMPLE_ACCESS" sk: "EXAMPLE_SECRET" }',
        'rados_info { key: "EXAMPLE_RADOS" }',
        'password = "two word password"',
        "accessKey=EXAMPLE_ACCESS",
        '"secretKey": "EXAMPLE_SECRET"',
        "--s3.ak EXAMPLE_ACCESS --s3.sk EXAMPLE_SECRET",
    ],
)
def test_text_credentials_are_redacted(text):
    result = redact(text)
    assert "EXAMPLE_" not in result and "two word password" not in result
    assert "[REDACTED]" in result


@pytest.mark.parametrize("module_name", ["safety", "remote_helper"])
def test_detail_output_can_keep_storage_keys(module_name):
    from importlib import import_module

    redact_output = import_module("dingofs_platform.resources." + module_name).redact
    value = {
        "result": {"fs_info": {"extra": {"s3_info": {
            "ak": "example-access", "sk": "example-secret",
        }}}},
        "password": "login-password",
    }
    revealed = redact_output(value, show_storage_keys=True)
    assert revealed["result"]["fs_info"]["extra"]["s3_info"] == {
        "ak": "example-access", "sk": "example-secret",
    }
    assert revealed["password"] == "[REDACTED]"
    hidden = redact_output(value)
    assert hidden["result"]["fs_info"]["extra"]["s3_info"]["sk"] == "[REDACTED]"


@pytest.mark.parametrize("action,expected", [
    ("fs.get", "example-secret"),
    ("fs.list", "[REDACTED]"),
    ("trash.get", "[REDACTED]"),
])
def test_remote_result_reveals_keys_only_for_filesystem_details(monkeypatch, capsys, action, expected):
    import json
    from dingofs_platform.resources import remote_helper

    monkeypatch.setattr(remote_helper, "run_command", lambda *a, **k: {
        "result": {"fs_info": {"extra": {"s3_info": {
            "ak": "example-access", "sk": "example-secret",
        }}}},
    })
    assert remote_helper.main({
        "action": action, "parameters": {}, "commands": [["dingo"]],
        "resource_id": "test-query",
    }) == 0
    result = json.loads(capsys.readouterr().out)
    result = redact(result, show_storage_keys=action == "fs.get")
    assert result["data"]["result"]["fs_info"]["extra"]["s3_info"]["sk"] == expected


def test_shared_operation_view_shows_detail_keys_without_private_access():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from dingofs_platform.resources.views import operation_view

    timestamp = datetime.now(timezone.utc)
    op = SimpleNamespace(
        id="detail", actor_id="creator", action="fs.get", state="succeeded",
        parameters={}, steps=[], cursor=0, error_code=None, resource_id=None,
        created_at=timestamp, expires_at=timestamp,
        result={"steps": [{"data": {"result": {"fs_info": {"extra": {
            "s3_info": {"ak": "example-access", "sk": "example-secret"},
        }}}}}]},
    )
    view = operation_view(None, op, private=False)
    keys = view["result"]["steps"][0]["data"]["result"]["fs_info"]["extra"]["s3_info"]
    assert keys == {"ak": "example-access", "sk": "example-secret"}
