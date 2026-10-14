from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from dingofs_platform.performance.remote_runner import prepare_target


def test_creates_nested_directory(tmp_path):
    target=tmp_path/'new'/'nested'
    assert prepare_target(str(target),'directory')==target
    assert target.is_dir()


def test_missing_mount_is_not_created(tmp_path):
    target=tmp_path/'missing'
    with pytest.raises(RuntimeError,match='尚未挂载'):
        prepare_target(str(target),'mount')
    assert not target.exists()


def test_sudo_creation_grants_only_target(tmp_path):
    target=tmp_path/'new'
    commands=[]
    original=Path.mkdir
    def run(argv,**kwargs):
        commands.append(argv)
        if argv[2]=='mkdir':original(target)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    with patch.object(Path,'mkdir',side_effect=PermissionError),patch('subprocess.run',side_effect=run):
        assert prepare_target(str(target),'directory')==target
    assert [c[2] for c in commands]==['mkdir','chown','chmod']
    assert all(c[:2]==['sudo','-n'] and c[-1]==str(target) for c in commands)
    assert all('-R' not in c for c in commands)


def test_sudo_error_is_visible(tmp_path):
    with patch.object(Path,'mkdir',side_effect=PermissionError),patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='sudo: a password is required',stdout='')):
        with pytest.raises(RuntimeError,match='password is required'):
            prepare_target(str(tmp_path/'new'),'directory')


def test_existing_file_rejected(tmp_path):
    target=tmp_path/'file';target.touch()
    with pytest.raises(RuntimeError,match='不是目录'):
        prepare_target(str(target),'directory')
