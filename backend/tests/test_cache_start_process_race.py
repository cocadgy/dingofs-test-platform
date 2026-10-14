from types import SimpleNamespace
import pytest
from dingofs_platform.resources import remote_helper as h


@pytest.mark.parametrize("persistent", [False, True])
def test_cache_launch_waits_for_unique_process(monkeypatch, tmp_path, persistent):
    state = {}
    class Store:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def load(self): return dict(state)
        def save(self, value): state.update(value)
    record = dict(state_dir=str(tmp_path / "state"), cache_dir=str(tmp_path / "cache"),
                  log_dir=str(tmp_path / "logs"), member_id="member", group_name="group")
    process = dict(pid=102, start_ticks="1", exe="/bin/dingo-cache",
                   argv=["dingo-cache", "--id=member", "--group_name=group",
                         "--log_dir=" + record["log_dir"]])
    scans = []
    def scan(path):
        scans.append(path)
        ids = [101, 102] if persistent or len(scans) == 1 else [102]
        return [SimpleNamespace(name=str(pid)) for pid in ids]
    monkeypatch.setattr(h, "OwnedState", lambda *a, **k: Store())
    monkeypatch.setattr(h, "mounted", lambda p: False)
    monkeypatch.setattr(h, "select_cache_port", lambda r: 21000)
    monkeypatch.setattr(h, "cache_argv", lambda r: ["dingo", "cache", "start"])
    launches = []
    monkeypatch.setattr(h, "_launch", lambda *a: launches.append(a) or SimpleNamespace(poll=lambda: 0))
    # No target-directory scan is needed; simulate a prior reserved/empty directory.
    real_scandir = h.os.scandir
    monkeypatch.setattr(h.os, "scandir", lambda p: scan(p) if p == "/proc" else real_scandir(p))
    monkeypatch.setattr(h, "process_identity", lambda pid: dict(process, pid=pid))
    monkeypatch.setattr(h, "_membership", lambda r: dict(group_name="group", state=1))
    clock = [0]
    monkeypatch.setattr(h.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(h.time, "sleep", lambda n: clock.__setitem__(0, clock[0] + n))
    req = dict(action="cache.create", resource_id="resource", record=record)
    if persistent:
        with pytest.raises(ValueError, match="multiple processes"):
            h.lifecycle(req)
        assert clock[0] >= 45
        assert "process" not in state
    else:
        status, _ = h.lifecycle(req)
        assert status == "running"
        assert len(scans) >= 2
        assert state["process"]["pid"] == 102
    assert len(launches) == 1
