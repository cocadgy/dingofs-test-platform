from pathlib import Path
import pytest
from dingofs_platform.performance import remote_runner


def executable(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('#!/bin/sh\nexit 0\n');path.chmod(0o755)
    return path


def test_existing_user_install_is_used(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    binary=executable(tmp_path/'bin/dtt')
    monkeypatch.setenv('PATH',str(binary.parent))
    assert remote_runner.resolve_dtt()==binary


def test_managed_install_has_priority(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    managed=executable(tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt')
    binary=executable(tmp_path/'bin/dtt');monkeypatch.setenv('PATH',str(binary.parent))
    assert remote_runner.resolve_dtt()==managed


def test_user_local_install_when_login_path_is_incomplete(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.setenv('PATH','')
    binary=executable(tmp_path/'.local/bin/dtt')
    assert remote_runner.resolve_dtt()==binary


def test_missing_or_nonexecutable_dtt_reports_checked_locations(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.setenv('PATH','')
    binary=executable(tmp_path/'.local/bin/dtt');binary.chmod(0o644)
    with pytest.raises(RuntimeError,match='PATH'):
        remote_runner.resolve_dtt()
