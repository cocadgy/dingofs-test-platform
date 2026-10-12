"""Filesystem listings may contain large per-MDS bucket distributions."""
import json
import sys

import pytest

from dingofs_platform.resources import remote_helper as helper


def list_request(script, action="fs.list"):
    return {
        "action": action,
        "parameters": {},
        "resource_id": "list-test",
        "commands": [[sys.executable, "-c", script, "--format", "json"]],
    }


def test_large_listing_preserves_every_filesystem_and_compacts_wire_json(tmp_path, capsys):
    rows = [
        {
            "fs_id": i,
            "fs_name": f"daily-文件-{i}",
            "extra": {"s3_info": {"ak": "access-value", "sk": "secret-value"}},
            "partition_policy": {"Partition": {"ParentHash": {
                "bucket_num": 1024,
                "distributions": {"1002": {"bucket_ids": list(range(1024))}},
            }}},
        }
        for i in range(80)
    ]
    data = {"error": {"code": 0}, "result": {"fs_infos": rows}}
    source = tmp_path / "listing.json"
    raw = json.dumps(data, indent=4)
    assert len(raw.encode()) > 1024 * 1024
    source.write_text(raw)
    request = list_request(f"import pathlib; print(pathlib.Path({str(source)!r}).read_text())")
    assert helper.main(request) == 0
    wire = capsys.readouterr().out
    reply = json.loads(wire)
    trace = reply["data"]["executed_commands"]
    assert len(trace) == 1 and trace[0]["status"] == "started"
    assert {k: v for k, v in reply["data"].items() if k != "executed_commands"} == helper.redact(data)
    assert len(wire.encode()) < len(raw.encode()) / 4
    assert len(wire.rstrip()) == len(json.dumps(reply, separators=(",", ":")))
    assert "access-value" not in wire and "secret-value" not in wire


@pytest.mark.parametrize("action,fd", [("fs.list", 1), ("fs.list", 2), ("fs.get", 1)])
def test_list_allowance_remains_bounded_and_does_not_enlarge_stderr_or_other_actions(
    action, fd, monkeypatch, capsys,
):
    # A small list allowance exercises the boundary without producing 32 MiB.
    monkeypatch.setattr(helper, "FS_LIST_MAX_OUTPUT", 4096, raising=False)
    size = 8192 if action == "fs.list" and fd == 1 else 2 * 1024 * 1024
    req = list_request(f"import os,time; os.write({fd}, b'x' * {size}); time.sleep(10)", action)
    assert helper.main(req) == 1
    reply = json.loads(capsys.readouterr().out)
    assert "command output exceeded limit" in reply["message"]
    assert reply["command_completed"] is False


def test_large_list_business_failure_is_still_a_failure(tmp_path, capsys):
    source = tmp_path / "failed-list.json"
    source.write_text(json.dumps({
        "error": {"code": 0},
        "result": {"error": {"errcode": "EINTERNAL", "errmsg": "MDS list denied"},
                   "padding": "x" * (1024 * 1024 + 1)},
    }))
    req = list_request(f"import pathlib; print(pathlib.Path({str(source)!r}).read_text())")
    assert helper.main(req) == 1
    reply = json.loads(capsys.readouterr().out)
    assert "MDS list denied" in reply["message"]
    assert reply["command_completed"] is True
