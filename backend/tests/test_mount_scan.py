import json
import os

import pytest

from dingofs_platform.resources import mount_scan as scan


def proc(tmp_path, argv=None, *, source="DingoFS:demo", path="/mnt/demo", pid=123):
    (tmp_path / "sys/kernel/random").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sys/kernel/random/boot_id").write_text("boot-test")
    (tmp_path / "self/ns").mkdir(parents=True, exist_ok=True)
    ns = tmp_path / "self/ns/mnt"
    if not ns.exists() and not ns.is_symlink():
        ns.symlink_to("mnt:[1]")
    (tmp_path / "self/mountinfo").write_text(
        f"42 1 0:53 / {path} rw - fuse.dingofs {source} rw\n"
    )
    if argv is not None:
        p = tmp_path / str(pid)
        (p / "ns").mkdir(parents=True, exist_ok=True)
        (p / "ns/mnt").symlink_to("mnt:[1]")
        (p / "exe").symlink_to("/opt/dingo-client")
        (p / "cmdline").write_bytes(b"\0".join(x.encode() for x in argv) + b"\0")
    return tmp_path


def test_uri_matching_and_saved_record_are_read_only(tmp_path):
    root = proc(tmp_path, ["dingo-client", "mds://b:6900,a:6900/demo", "/mnt/demo", "--password=hidden"])
    before = (root / "self/mountinfo").read_bytes()
    data = scan.scan_mounts("a:6900,b:6900", {"/mnt/demo": "saved"}, proc_root=root)
    row = data["mounts"][0]
    assert row["cluster_match"] == "current"
    assert row["pid"] == 123 and row["saved_resource_id"] == "saved"
    assert row["fs_name"] == "demo" and row["client_user"]
    assert not row["cleanup_allowed"]
    assert "hidden" not in json.dumps(data) and "argv" not in json.dumps(data)
    assert (root / "self/mountinfo").read_bytes() == before


@pytest.mark.parametrize("argv", [
    ["dingo-client", "--mountpoint=/mnt/demo", "--fsname=demo", "--mdsaddr=other:6900"],
    ["dingo-client", "--mountpoint", "/mnt/demo", "--fs_name", "demo", "--mds_addrs", "other:6900"],
])
def test_other_cluster_is_not_assigned_by_fs_name(tmp_path, argv):
    row = scan.scan_mounts("a:6900", proc_root=proc(tmp_path, argv))["mounts"][0]
    assert row["cluster_match"] == "other"
    assert row["mds_addresses"] == ["other:6900"]


def test_escaped_path_and_absent_process_remain_visible(tmp_path):
    row = scan.scan_mounts("a:6900", proc_root=proc(tmp_path, path=r"/mnt/a\040b"))["mounts"][0]
    assert row["mount_path"] == "/mnt/a b"
    assert row["cluster_match"] == "unknown" and row["reason"]
    assert row["cleanup_allowed"]
    assert row["kernel_mount"]["mount_path"] == "/mnt/a b"


def test_ambiguous_processes_are_unknown(tmp_path):
    argv = ["dingo-client", "mds://a:6900/demo", "/mnt/demo"]
    proc(tmp_path, argv, pid=123)
    proc(tmp_path, argv, pid=124)
    row = scan.scan_mounts("a:6900", proc_root=tmp_path)["mounts"][0]
    assert row["cluster_match"] == "unknown" and row["pid"] is None
    assert not row["cleanup_allowed"]


def test_unreadable_mount_table_is_failure_not_empty(tmp_path):
    with pytest.raises((OSError, ValueError)):
        scan.scan_mounts("a:6900", proc_root=tmp_path)


def test_process_in_other_namespace_is_not_used(tmp_path):
    proc(tmp_path, ["dingo-client", "mds://a:6900/demo", "/mnt/demo"])
    ns = tmp_path / "123/ns/mnt"
    ns.unlink()
    ns.symlink_to("mnt:[2]")
    row = scan.scan_mounts("a:6900", proc_root=tmp_path)["mounts"][0]
    assert row["cluster_match"] == "unknown"


def test_scan_limit_is_reported(tmp_path):
    proc(tmp_path)
    with pytest.raises(ValueError, match="上限"):
        scan.scan_mounts("a:6900", proc_root=tmp_path, max_mounts=0)
