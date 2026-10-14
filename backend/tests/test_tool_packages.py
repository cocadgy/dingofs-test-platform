import hashlib
import json
from pathlib import Path
import pytest
from dingofs_platform.tool_packages.bundle import inspect_bundle
from dingofs_platform.tool_packages.remote import probe_script, install_script


def bundle(tmp_path, tool='dingo'):
    root = tmp_path / 'v1'
    root.mkdir()
    (root / tool).write_text('#!/bin/sh\necho version\n')
    manifest = {'tool': tool, 'version': 'v1', 'architecture': 'x86_64', 'entrypoint': tool,
                'files': {tool: hashlib.sha256((root / tool).read_bytes()).hexdigest()}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root, manifest


def test_inspect_bundle_is_content_addressed(tmp_path):
    root, manifest = bundle(tmp_path)
    result = inspect_bundle(tmp_path, 'v1')
    assert result['tool'] == 'dingo'
    assert result['size_bytes'] > 0
    assert len(result['digest']) == 64
    (root / 'dingo').write_text('changed')
    with pytest.raises(ValueError, match='校验'):
        inspect_bundle(tmp_path, 'v1')


def test_reject_outside_path_and_symlink(tmp_path):
    root, manifest = bundle(tmp_path)
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, '../elsewhere')
    (root / 'dingo').unlink()
    (root / 'dingo').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, 'v1')


def test_dtt_requires_image_and_companions(tmp_path):
    root, manifest = bundle(tmp_path, 'dtt')
    with pytest.raises(ValueError, match='镜像'):
        inspect_bundle(tmp_path, 'v1')


def test_remote_scripts_do_not_overwrite_system_tools():
    code = install_script({'tool':'dingo', 'digest':'a'*64, 'entrypoint':'dingo',
                           'architecture':'x86_64', 'files':{'dingo':'b'*64}}, '/tmp/tool-stage')
    assert '/usr/local/bin' not in code
    assert 'sha256' in code
    assert 'os.replace' in code
    assert 'dingo-cache' in probe_script()


def test_install_runs_verification_then_activates_without_touching_existing(tmp_path, monkeypatch):
    import os
    import subprocess
    root, manifest = bundle(tmp_path)
    manifest['digest'] = 'a' * 64
    home = tmp_path / 'home'
    home.mkdir()
    existing = home / 'bin/dingo'
    existing.parent.mkdir()
    existing.write_text('existing installation')
    env = dict(os.environ, HOME=str(home))
    result = subprocess.run(['python3', '-c', install_script(manifest, str(root))], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    installed = home / '.local/share/dingofs-platform/tools/dingo/current/dingo'
    assert installed.is_file()
    assert existing.read_text() == 'existing installation'
    assert json.loads(result.stdout.splitlines()[-1])['installed_path'] == str(installed)


def test_failed_verification_does_not_activate(tmp_path):
    import os
    import subprocess
    root, manifest = bundle(tmp_path)
    (root/'dingo').write_text('#!/bin/sh\nexit 1\n')
    manifest['files']['dingo'] = hashlib.sha256((root/'dingo').read_bytes()).hexdigest()
    manifest['digest'] = 'b'*64
    result = subprocess.run(['python3','-c',install_script(manifest,str(root))],env=dict(os.environ,HOME=str(tmp_path/'home')),capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path/'home/.local/share/dingofs-platform/tools/dingo/current').exists()


def test_dtt_probe_rejects_missing_image_and_does_not_expose_config_secrets(tmp_path):
    import os
    import subprocess
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir/'dtt').write_text('#!/bin/sh\nif [ "$1" = config ]; then echo "  image: absent:test"; echo "  webhook_url: private-secret"; else echo dtt; fi\n')
    (bin_dir/'docker').write_text('#!/bin/sh\nif [ "$1" = info ]; then exit 0; fi\necho "No such image"; exit 1\n')
    for path in bin_dir.iterdir(): path.chmod(0o755)
    env = dict(os.environ, HOME=str(tmp_path), PATH=str(bin_dir)+':/usr/local/bin:/usr/bin:/bin')
    result = subprocess.run(['python3','-c',probe_script()],env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    record = next(item for item in json.loads(result.stdout)['items'] if item['tool']=='dtt')
    assert record['status'] == 'unavailable'
    assert 'private-secret' not in result.stdout


def test_client_help_exit_one_is_not_an_install_failure(tmp_path):
    import os
    import subprocess
    root, manifest = bundle(tmp_path, 'dingo-client')
    (root/'dingo-client').write_text('#!/bin/sh\nprintf "dingo-client main-abcdef [local]\\nUsage:\\n  dingo-client [OPTIONS] <meta-url> <mountpoint>\\n"\nexit 1\n')
    manifest['files']['dingo-client'] = hashlib.sha256((root/'dingo-client').read_bytes()).hexdigest()
    manifest['digest'] = 'c'*64
    result = subprocess.run(['python3','-c',install_script(manifest,str(root))],env=dict(os.environ,HOME=str(tmp_path/'home')),capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_dtt_install_uses_pinned_image_and_isolated_configuration(tmp_path):
    import os
    import subprocess
    root=tmp_path/'stage'
    root.mkdir()
    (root/'dingofs-testsuite-tool').write_text('#!/bin/sh\nif [ "$1" = config ]; then printf "image: "; cat "$DINGOFS_TESTSUITE_CONFIG_DIR/image"; printf "runtime: "; cat "$DINGOFS_TESTSUITE_CONFIG_DIR/runtime"; else echo dtt-help; fi\n')
    for name in ('image.tar','dtt-ai-analyze','analysis.schema.json'):
        (root/name).write_text('fixture')
    manifest={'tool':'dtt','entrypoint':'dingofs-testsuite-tool','version':'v1','architecture':__import__('platform').machine(),'digest':'d'*64,'image_id':'sha256:'+'a'*64,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
    (root/'manifest.json').write_text(json.dumps(manifest))
    bindir=tmp_path/'bin';bindir.mkdir()
    (bindir/'docker').write_text('#!/bin/sh\necho "$*" >> "$HOME/docker-commands"\nexit 0\n')
    (bindir/'docker').chmod(0o755)
    home=tmp_path/'home';home.mkdir()
    env=dict(os.environ,HOME=str(home),PATH=str(bindir)+':/usr/local/bin:/usr/bin:/bin')
    result=subprocess.run(['python3','-c',install_script(manifest,str(root))],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    installed=home/'.local/share/dingofs-platform/tools/dtt/current'
    result=subprocess.run([str(installed/'dtt'),'config','show'],env=env,capture_output=True,text=True)
    assert manifest['image_id'] in result.stdout
    assert not (installed/'image.tar').exists()
    commands=(home/'docker-commands').read_text()
    assert '--entrypoint fio '+manifest['image_id']+' --version' in commands
    assert '--entrypoint elbencho '+manifest['image_id']+' --version' in commands
    assert 'pull ' not in commands


def test_cache_legacy_help_exit_255_is_supported():
    from dingofs_platform.tool_packages.help_result import help_succeeded
    assert help_succeeded('dingo-cache',255,'dingo-cache main\nUsage:\n dingo-cache [OPTIONS] --id <cache_node_uuid>\n')
    assert not help_succeeded('dingo-cache',255,'error while loading shared libraries')
