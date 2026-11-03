import os
import stat
import subprocess

import pytest

from dingofs_platform.resources import cache_directory as mod


def test_normal_creation_and_existing_permissions_unchanged(tmp_path):
    base = tmp_path / "nested" / "cache"
    mod.prepare_cache_directory(str(base))
    assert stat.S_IMODE(base.stat().st_mode) == 0o750
    base.chmod(0o700)
    (base / "existing").write_text("keep")
    mod.prepare_cache_directory(str(base))
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert (base / "existing").read_text() == "keep"


def test_symlinks_rejected_without_changing_target(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(actual)
    with pytest.raises((ValueError, OSError)):
        mod.prepare_cache_directory(str(tmp_path / "link" / "cache"))
    assert list(actual.iterdir()) == []
    assert stat.S_IMODE(actual.stat().st_mode) == 0o700


def test_sudo_only_after_permission_failure_and_rechecks(tmp_path, monkeypatch):
    base = tmp_path / "cache"
    original = mod.create_directory
    calls = []
    def denied(*args, **kwargs):
        raise PermissionError("denied")
    def sudo(argv, **kwargs):
        calls.append((argv, kwargs))
        original(str(base), os.geteuid(), os.getegid())
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(mod, "create_directory", denied)
    monkeypatch.setattr(mod.subprocess, "run", sudo)
    mod.prepare_cache_directory(str(base))
    assert base.is_dir()
    assert calls[0][0][:3] == ["sudo", "-n", "--"]
    assert calls[0][1]["timeout"] == 30


def test_existing_inaccessible_directory_never_uses_sudo(tmp_path, monkeypatch):
    base = tmp_path / "cache"
    base.mkdir(mode=0o700)
    monkeypatch.setattr(mod.os, "access", lambda *a, **k: False)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: pytest.fail("must not sudo"))
    with pytest.raises(ValueError, match="权限"):
        mod.prepare_cache_directory(str(base))
    assert stat.S_IMODE(base.stat().st_mode) == 0o700


def test_sudo_denial_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "create_directory", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "password required"))
    with pytest.raises(ValueError, match="sudo"):
        mod.prepare_cache_directory(str(tmp_path / "cache"))

def test_privileged_helper_assigns_only_new_base_to_execution_user(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("root-only ownership check in isolated test container")
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o755)
    before = parent.stat()
    base = parent / "cache"
    mod.create_directory(str(base), 65534, 65534)
    assert base.stat().st_uid == 65534
    assert base.stat().st_gid == 65534
    assert stat.S_IMODE(base.stat().st_mode) == 0o750
    assert (parent.stat().st_uid, parent.stat().st_mode) == (before.st_uid, before.st_mode)
    mod.create_directory(str(base), 0, 0)
    assert base.stat().st_uid == 65534


@pytest.mark.parametrize("path", ["/", "/tmp/../cache", "/tmp//cache"])
def test_unsafe_paths_rejected(path):
    with pytest.raises(ValueError):
        mod.prepare_cache_directory(path)


def test_concurrent_creator_is_not_reowned(tmp_path, monkeypatch):
    real = mod.os.mkdir
    base = tmp_path / "cache"
    def racing(name, mode=0o777, **kwargs):
        result = real(name, mode, **kwargs)
        if str(name).startswith(".dtt-cache-"):
            real(base, 0o700)
        return result
    monkeypatch.setattr(mod.os, "mkdir", racing)
    with pytest.raises(FileExistsError):
        mod.create_directory(str(base), 65534, 65534)
    assert base.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert list(tmp_path.iterdir()) == [base]

def test_root_stages_outside_user_writable_parent(tmp_path, monkeypatch):
    if os.geteuid() != 0:
        pytest.skip("root-only staging check")
    parent = tmp_path / "user-writable"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    protected = tmp_path / "existing-data"
    protected.mkdir(mode=0o755)
    (protected / "data").write_text("keep")
    original_open = mod.os.open
    parent_inode = parent.stat().st_ino
    def swapped_open(path, flags, *args, **kwargs):
        fd = kwargs.get("dir_fd")
        if str(path).startswith(".dtt-cache-") and fd is not None and os.fstat(fd).st_ino == parent_inode:
            os.rmdir(path, dir_fd=fd)
            os.rename(protected, path, dst_dir_fd=fd)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(mod.os, "open", swapped_open)
    mod.create_directory(str(parent / "cache"), 65534, 65534)
    assert protected.is_dir()
    assert stat.S_IMODE(protected.stat().st_mode) == 0o755
    assert (protected / "data").read_text() == "keep"
    assert (parent / "cache").stat().st_uid == 65534

def test_search_only_ancestor_does_not_require_read_permission(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("requires unprivileged traversal")
    parent = tmp_path / "search-only"
    parent.mkdir()
    base = parent / "cache"
    base.mkdir(mode=0o750)
    parent.chmod(0o111)
    try:
        assert os.access(base, os.R_OK | os.W_OK | os.X_OK)
        mod.prepare_cache_directory(str(base))
        assert stat.S_IMODE(parent.stat().st_mode) == 0o111
    finally:
        parent.chmod(0o700)
