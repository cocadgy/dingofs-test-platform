import os
import subprocess
from pathlib import Path
from dingofs_platform.tool_packages.shell_entry import install_shell_entry


def fixture(home):
    current=home/'.local/share/dingofs-platform/tools/dtt/current'
    current.mkdir(parents=True)
    command=current/'dtt'
    command.write_text('#!/bin/sh\nprintf "managed-dtt:%s\\n" "$*"\n')
    command.chmod(0o755)
    return current


def test_direct_command_in_new_bash_shell_and_old_alias_replaced(tmp_path):
    fixture(tmp_path)
    (tmp_path/'.bashrc').write_text("export KEEP_ME=yes\nalias dtt='echo old'\n")
    install_shell_entry(tmp_path)
    result=subprocess.run(['bash','--noprofile','--rcfile',str(tmp_path/'.bashrc'),'-ic','dtt --help'],env=dict(os.environ,HOME=str(tmp_path)),capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'managed-dtt:--help' in result.stdout
    assert 'export KEEP_ME=yes' in (tmp_path/'.bashrc').read_text()


def test_existing_commands_backed_up_and_profiles_are_idempotent(tmp_path):
    fixture(tmp_path)
    bindir=tmp_path/'.local/bin';bindir.mkdir(parents=True)
    (bindir/'dtt').write_text('old-command')
    (tmp_path/'.profile').write_text('export KEEP_PROFILE=yes\n')
    first=install_shell_entry(tmp_path)
    second=install_shell_entry(tmp_path)
    assert first['command_path']==str(bindir/'dtt')
    assert (tmp_path/'.profile').read_text().count('# BEGIN DINGOFS PLATFORM DTT')==1
    assert not (tmp_path/'.bash_profile').exists()
    assert any(p.read_text()=='old-command' for p in bindir.glob('dtt.before-platform-*'))
    assert not second['backups']
    result=subprocess.run(['bash','--noprofile','--norc','-c','. "$HOME/.profile"; dtt config show'],env=dict(os.environ,HOME=str(tmp_path)),capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'managed-dtt:config show' in result.stdout


def test_uses_existing_bash_login_file_and_configures_zsh(tmp_path):
    fixture(tmp_path)
    (tmp_path/'.bash_profile').write_text('# login settings\n')
    install_shell_entry(tmp_path)
    assert 'DINGOFS PLATFORM DTT' in (tmp_path/'.bash_profile').read_text()
    assert 'DINGOFS PLATFORM DTT' in (tmp_path/'.zshrc').read_text()
    assert 'DINGOFS PLATFORM DTT' in (tmp_path/'.zprofile').read_text()
