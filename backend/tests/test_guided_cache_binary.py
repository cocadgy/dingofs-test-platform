import io
import json
from types import SimpleNamespace
import pytest
from dingofs_platform.resources import cache_binary as binary, commands, remote_helper as helper, port_planning


def test_commit_lookup_requires_published_artifact(monkeypatch):
    index = {"commits": {"fe4384a": {"path": "commits/fe4384a/dingo-cache", "build_time": "now", "size": "34MB"}}}
    monkeypatch.setattr(binary.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(index).encode()))
    assert binary.resolve_cache_commit("fe4384a")["url"].endswith("/commits/fe4384a/dingo-cache")
    with pytest.raises(ValueError, match="未找到"):
        binary.resolve_cache_commit("abcdef0")
    with pytest.raises(ValueError):
        binary.resolve_cache_commit("../bad")


def test_explicit_directory_is_used_and_changed_file_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "dingo-cache"
    path.write_bytes(b"test-binary")
    path.chmod(0o700)
    monkeypatch.setattr(binary.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"main-fe4384a0b"))
    info = binary.prepare_cache_binary({"binary_source": "path", "binary_directory": str(tmp_path)})
    record = dict(binary_source="path", binary_info=info, member_id="id", group_name="group", listen_ip="127.0.0.1",
                  listen_port=21000, cache_dir="/tmp/cache", cache_size_mb=1, log_dir="/tmp/log", use_rdma=False)
    assert helper.cache_argv({"record": record, "mds_addr": "127.0.0.1:6900"})[0] == str(path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="发生变化"):
        helper.cache_argv({"record": record, "mds_addr": "127.0.0.1:6900"})


def test_download_failure_is_explicit_and_has_no_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(binary.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(binary, "resolve_cache_commit", lambda commit: {"commit": commit, "url": "https://example.invalid/bin"})
    def fail(*a, **k):
        raise OSError("network unreachable")
    monkeypatch.setattr(binary.urllib.request, "urlopen", fail)
    with pytest.raises(ValueError, match="下载或验证.*失败"):
        binary.prepare_cache_binary({"binary_source": "commit", "binary_commit": "fe4384a"})
    assert not list(tmp_path.rglob("dingo-cache"))


def test_requested_commit_must_match_downloaded_version(tmp_path, monkeypatch):
    path = tmp_path / "dingo-cache"
    path.write_bytes(b"test")
    path.chmod(0o700)
    monkeypatch.setattr(binary.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"main-abcdef00"))
    with pytest.raises(ValueError, match="不一致"):
        binary.inspect_cache_binary(path, "fe4384a")


def test_guided_binary_input_is_validated_and_legacy_default_remains_supported():
    member = dict(machine_id="m", target_user="u", listen_ip="127.0.0.1", cache_dir="/tmp/cache")
    assert commands.validate("cache.plan", {"group_name": "g", "members": [member]})
    with pytest.raises(ValueError, match="binary_commit"):
        commands.validate("cache.plan", {"group_name": "g", "members": [{**member, "binary_source": "commit", "binary_commit": "../x"}]})
    with pytest.raises(ValueError, match="binary_directory"):
        commands.validate("cache.plan", {"group_name": "g", "members": [{**member, "binary_source": "path", "binary_directory": "relative"}]})


def test_remote_script_embeds_binary_preparation():
    member = dict(machine_id="m", target_user="u", listen_ip="127.0.0.1", cache_dir="/tmp/cache", group_name="g")
    record = {**member, "state_dir": "/tmp/state", "log_dir": "/tmp/log"}
    script = commands.build_script("cache.plan", member, "127.0.0.1:6900", "r", record=record)
    assert "def prepare_cache_binary" in script
    assert "from .cache_binary" not in script


def test_retry_preserves_member_ids_and_skips_successes(monkeypatch):
    from dingofs_platform.resources import execution
    from dingofs_platform.resources.models import ResourceOperation, ManagedResource
    from dingofs_platform.errors import Problem
    members = [{"member_id": "done", "process_state": "running"}, {"member_id": "failed", "process_state": "unknown"}, {"member_id": "waiting", "process_state": "not_started"}]
    previous = SimpleNamespace(action="cache.create", actor_id="u", cluster_id="c", state="failed", resource_id="r", steps=[{"record": member, "action": "cache.create"} for member in members])
    resource = SimpleNamespace(state="partial", data={"members": members})
    db = SimpleNamespace(get=lambda model, id: previous if model is ResourceOperation else resource)
    monkeypatch.setattr(execution, "valid", lambda *a: True)
    work, actual = port_planning.retry_creation(db, SimpleNamespace(id="u"), SimpleNamespace(id="c"), "op")
    assert [item["record"]["member_id"] for item in work] == ["failed", "waiting"]
    assert actual is resource
    with pytest.raises(Problem):
        port_planning.retry_creation(db, SimpleNamespace(id="other"), SimpleNamespace(id="c"), "op")
