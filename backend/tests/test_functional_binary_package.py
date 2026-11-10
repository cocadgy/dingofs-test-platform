import json
import subprocess
from pathlib import Path
import dingofs_platform.tool_packages as package
import hashlib
import os
import platform
import pytest
from dingofs_platform.tool_packages.automatic import helper


FEATURES = ['exact_case_plan_v1','runtime_context_v1','owned_cleanup_v1',
            'lifecycle_events_v2','cancel_boundary_v1','inspection_v1']
REQUIRED = ['run_tests.py','requirements.txt','pytest.ini',
            'src/test_runner/functional_plan.py','src/test_runner/runtime_context.py',
            'src/test_runner/resource_journal.py','src/test_runner/owned_resources.py',
            'src/test_runner/functional_events.py','src/test_runner/functional_redaction.py',
            'src/test_runner/functional_contracts.py','src/test_runner/functional_capabilities.py',
            'src/config/ssh_client.py','src/config/env_parser.py']


def complete_source(root):
    root.mkdir()
    for name in ('dingofs-testsuite-tool','entrypoint.sh','functional_runtime.py','dtt-ai-analyze','analysis.schema.json'):
        (root/name).write_text('synthetic launcher')
    source=root/'dingofs-integration-test'
    optional=['src/config/env_setup.py','src/config/command_utils.py','src/test_runner/test_suite.py',
        'src/client_test/mixins/mount_ops.py','src/client_test/mixins/cache_group_ops.py',
        'src/large_scale_test/cache_setup.py','src/large_scale_test/cache_observer.py',
        *['src/'+module+'_test/executor.py' for module in ('mount_subdir','trash','cache_node','hot_upgrade','dirstat','mds_manage')]]
    for name in REQUIRED+optional+['conf/env/base.yaml','conf/storage.yaml','testcases/quota_test_cases/case.yaml',
                          'testcases/quota_test_cases/include.yaml','tools/runtime_dependency.sh']:
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('synthetic-password' if name.startswith('conf/') else 'fixture')
    (source/'functional_protocol.json').write_text(json.dumps({'version':2,'features':FEATURES,'context_version':1,'event_version':2}))
    return source


def source_result(root):
    # Only stdlib source enumeration is executed. Every subprocess/network API
    # inside the remote helper is denied (there is no Docker/SSH in this test).
    import io
    from contextlib import redirect_stdout
    from unittest.mock import patch
    output=io.StringIO()
    with patch('subprocess.run',side_effect=AssertionError('Unexpected subprocess')), patch('socket.socket',side_effect=AssertionError('Unexpected network')), redirect_stdout(output):
        exec(helper({'operation':'source_files','directory':str(root),'tool':'dtt'}),{})
    return json.loads(output.getvalue())


def test_complete_source_paths_and_hashes_are_preserved(tmp_path):
    root=tmp_path/'source with spaces';source=complete_source(root)
    result=source_result(root)
    expected={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    assert result.get('source_manifest')==expected
    assert all(result['files']['dingofs-integration-test/'+name]['sha256']==sha for name,sha in expected.items())
    assert 'synthetic-password' not in json.dumps(result)


@pytest.mark.parametrize('missing',['src/test_runner/functional_events.py','requirements.txt','functional_protocol.json'])
def test_incomplete_framework_does_not_advertise_protocol(tmp_path,missing):
    root=tmp_path/'source';source=complete_source(root)
    (source/missing).unlink()
    with pytest.raises((ValueError,RuntimeError),match='functional|protocol|runtime'):
        source_result(root)


def test_source_symlink_rejected(tmp_path):
    root=tmp_path/'source';source=complete_source(root)
    (source/'src/escape.py').symlink_to('/etc/passwd')
    with pytest.raises((ValueError,RuntimeError),match='symlink'):
        source_result(root)


def test_internal_case_alias_is_materialized_without_package_symlink(tmp_path,monkeypatch):
    root=tmp_path/'source';source=complete_source(root)
    target=source/'testcases/quota_test_cases/case.yaml'
    alias=source/'testcases/quota_test_cases/smoke/alias.yaml'
    alias.parent.mkdir();alias.symlink_to('../case.yaml')
    result=source_result(root)
    assert result['source_manifest']['testcases/quota_test_cases/smoke/alias.yaml']==hashlib.sha256(target.read_bytes()).hexdigest()
    alias_info=result['files']['dingofs-integration-test/testcases/quota_test_cases/smoke/alias.yaml']
    assert not Path(alias_info['path']).is_symlink()
    assert Path(alias_info['path'])==target
    assert result['source_aliases']=={'testcases/quota_test_cases/smoke/alias.yaml':'testcases/quota_test_cases/case.yaml'}


def test_offline_and_automatic_share_complete_manifest(tmp_path,monkeypatch):
    import runpy
    import sys
    root=tmp_path/'source';complete_source(root)
    automatic=source_result(root)
    output=tmp_path/'output'
    calls=[]
    def inspect(argv):
        assert argv==['docker','image','inspect','local-image']
        calls.append(argv)
        return json.dumps([{'Id':'sha256:'+'a'*64,'Architecture':'amd64','Os':'linux'}])
    def save(argv,**kwargs):
        assert argv[:3]==['docker','save','-o']
        calls.append(argv)
        Path(argv[3]).write_text('synthetic image archive')
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(subprocess,'check_output',inspect)
    monkeypatch.setattr(subprocess,'run',save)
    monkeypatch.setattr(sys,'argv',['prepare-tool-bundle.py','--tool','dtt','--version','test',
        '--source',str(root),'--image','local-image','--output',str(output)])
    script=Path(__file__).resolve().parents[2]/'scripts/prepare-tool-bundle.py'
    runpy.run_path(str(script),run_name='__main__')
    bundle=output/'dtt-test-x86_64'
    manifest=json.loads((bundle/'manifest.json').read_text())
    assert manifest['source_manifest']==automatic['source_manifest']
    assert all(manifest['files'][name]==value['sha256'] for name,value in automatic['files'].items())
    assert len(calls)==2
    assert (bundle/'dingofs-integration-test/conf/storage.yaml').stat().st_mode & 0o777 == 0o600
    from dingofs_platform.tool_packages.bundle import inspect_bundle
    assert inspect_bundle(output,bundle.name)['source_manifest']==automatic['source_manifest']


def test_install_only_parent_creation_is_private_and_bounded(tmp_path,monkeypatch):
    import io
    from contextlib import redirect_stdout
    from unittest.mock import patch
    monkeypatch.setenv('HOME',str(tmp_path))
    stage=tmp_path/'.local/share/dingofs-platform/staging/auto-fixture'
    stage.mkdir(parents=True)
    request={'operation':'parents','staging':str(stage),'name':'dingofs-integration-test/conf/env/base.yaml'}
    with patch('subprocess.run',side_effect=AssertionError('Unexpected subprocess')), redirect_stdout(io.StringIO()):
        exec(helper(request),{})
    assert (stage/'dingofs-integration-test/conf/env').stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError,match='Invalid'):
        exec(helper({**request,'name':'../escape'}),{})


def test_unconfirmed_cached_image_never_exports(monkeypatch,tmp_path):
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv,1 if 'pull' in argv else 0,b'offline')
    monkeypatch.setattr(subprocess,'run',run)
    monkeypatch.setattr('shutil.which',lambda name:'/fake/'+name)
    with pytest.raises(RuntimeError,match='未允许'):
        exec(helper({'operation':'export','image':'local','architecture':platform.machine(),'allow_cached':False}),{})
    assert [call[1] for call in calls]==['info','pull']


def test_install_returns_pinned_executable_capability_and_private_sources(tmp_path):
    from dingofs_platform.tool_packages.remote import install_script
    root=tmp_path/'stage';source=complete_source(root)
    image='sha256:'+'a'*64
    source_manifest={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    # Harmless synthetic wrapper reads exactly the generated capability record.
    (root/'dingofs-testsuite-tool').write_text('#!/usr/bin/env python3\nimport json,pathlib,sys\n'
        'if "--functional-capabilities" in sys.argv: print(json.dumps(json.loads((pathlib.Path(__file__).parent/"functional-runtime.json").read_text())["functional_runtime"]))\n'
        'else: print("dtt help")\n')
    files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    bundle={'tool':'dtt','entrypoint':'dingofs-testsuite-tool','version':'v1','architecture':platform.machine(),
            'digest':'d'*64,'image_id':image,'files':files,'source_manifest':source_manifest,'functional_features':FEATURES}
    (root/'manifest.json').write_text(json.dumps(bundle))
    bindir=tmp_path/'bin';bindir.mkdir()
    (bindir/'docker').write_text('#!/bin/sh\ncase "$1" in info|image|run) exit 0;; *) exit 99;; esac\n')
    (bindir/'docker').chmod(0o755)
    home=tmp_path/'home';home.mkdir()
    result=subprocess.run(['python3','-c',install_script(bundle,str(root))],env=dict(os.environ,HOME=str(home),PATH=str(bindir)+':'+os.environ['PATH']),capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    installed=json.loads(result.stdout.splitlines()[-1])
    assert 'immutable_path' in installed
    immutable=Path(installed['immutable_path'])
    assert immutable.is_absolute() and immutable.name=='dtt' and immutable.is_file()
    assert not {'current','latest'} & set(immutable.parts)
    assert installed['execution_user']==__import__('pwd').getpwuid(os.geteuid()).pw_name
    generated={name:hashlib.sha256((immutable.parent/name).read_bytes()).hexdigest() for name in ('dtt','config/image','config/runtime','functional-aliases.json')}
    assert installed['functional_runtime']=={'version':2,'features':FEATURES,'files':{**files,**generated},'image_id':image,'source_manifest':source_manifest}
    secret=immutable.parent/'dingofs-integration-test/conf/storage.yaml'
    assert secret.stat().st_mode & 0o777 == 0o600
    assert secret.parent.stat().st_mode & 0o777 == 0o700
    assert (immutable.parent/'dingofs-integration-test/tools/runtime_dependency.sh').stat().st_mode & 0o777 == 0o700


def test_legacy_bundle_keeps_binary_overlays(tmp_path):
    source=tmp_path/'legacy';source.mkdir()
    for name in ('dingofs-testsuite-tool','dtt-ai-analyze','analysis.schema.json'):
        (source/name).write_text('fixture')
    names={'run_tests.py':'run_tests.py','test_suite.py':'src/test_runner/test_suite.py','functional_plan.py':'src/test_runner/functional_plan.py',
        'env_parser.py':'src/config/env_parser.py','env_setup.py':'src/config/env_setup.py','command_utils.py':'src/config/command_utils.py',
        'client_mount_ops.py':'src/client_test/mixins/mount_ops.py','client_cache_group_ops.py':'src/client_test/mixins/cache_group_ops.py',
        'large_scale_cache_setup.py':'src/large_scale_test/cache_setup.py','large_scale_cache_observer.py':'src/large_scale_test/cache_observer.py',
        **{name+'_executor.py':'src/'+name+'_test/executor.py' for name in ('mount_subdir','trash','cache_node','hot_upgrade','dirstat','mds_manage')}}
    for relative in names.values():
        path=source/'dingofs-integration-test'/relative
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
    helper=Path(package.__file__).parent/'automatic_helper.py'
    script='REQUEST='+repr({'operation':'source_files','directory':str(source),'tool':'dtt'})+'\n'+helper.read_text()
    result=subprocess.run(['python3','-c',script],capture_output=True,text=True,check=True)
    files=json.loads(result.stdout)['files']
    for name in ('env_setup.py','command_utils.py','mount_subdir_executor.py','cache_node_executor.py','trash_executor.py'):
        assert name in files


def test_actual_wrapper_installer_interop_on_synthetic_framework(tmp_path):
    import shutil
    wrapper_source=os.environ.get('DTT_TEST_SOURCE')
    if not wrapper_source:
        pytest.skip('Set DTT_TEST_SOURCE for cross-repository wrapper/package integration')
    from dingofs_platform.tool_packages.remote import install_script
    root=tmp_path/'stage';complete_source(root)
    source=root/'dingofs-integration-test'
    (source/'conf/env/base.yaml').write_text('env_original:\n  mds_addr: 192.0.2.1:6700\n  host: 192.0.2.1\n  ssh_user: tester\n  run_as_user: tester/fixture-secret\n  dingo_tool_path: /bin/dingo\n  mds_client_path: /bin/mds-client\n  storage: {storage_type: s3, storage_env: fixture}\n  clients: [{host: 192.0.2.2, fs_name: fixture, mount_path: /mnt/fixture}]\n')
    (source/'conf/storage.yaml').write_text('fixture:\n  s3: {s3_ak: fixture-secret, s3_sk: fixture-secret, s3_endpoint: http://store, s3_bucketname: bucket}\n')
    (source/'testcases/quota_test_cases/case.yaml').write_text('case_name: fixture\nsteps: [{include: include.yaml}]\n')
    (source/'testcases/quota_test_cases/include.yaml').write_text('[]\n')
    (source/'testcases/quota_test_cases/smoke').mkdir()
    (source/'testcases/quota_test_cases/smoke/alias.yaml').symlink_to('../case.yaml')
    for name in ('dingofs-testsuite-tool','entrypoint.sh','functional_runtime.py'):
        shutil.copyfile(Path(wrapper_source)/name,root/name)
    metadata=source_result(root)
    original=tmp_path/'original-source'
    shutil.copytree(source,original,symlinks=True)
    # Emulate SCP/SFTP transfer: alias bytes arrive as a regular file; the
    # immutable installer alone is authorized to reconstruct declared links.
    for alias,target in metadata.get('source_aliases',{}).items():
        path=source/alias;path.unlink();path.write_bytes((source/target).read_bytes())
    files={name:record['sha256'] for name,record in metadata['files'].items()}
    image='sha256:'+'a'*64
    bundle={'tool':'dtt','entrypoint':'dingofs-testsuite-tool','version':'v1','architecture':platform.machine(),
        'digest':'e'*64,'image_id':image,'files':files,'source_manifest':metadata['source_manifest'],'functional_features':FEATURES,'source_aliases':metadata.get('source_aliases',{})}
    (root/'manifest.json').write_text(json.dumps(bundle))
    bindir=tmp_path/'bin';bindir.mkdir()
    info=json.dumps([{'Id':image,'Architecture':{'x86_64':'amd64','aarch64':'arm64'}[platform.machine()],'Os':'linux'}])
    (bindir/'docker').write_text('#!/usr/bin/env python3\nimport sys\n'
        'if sys.argv[1:3]==["image","inspect"]: print('+repr(info)+')\n'
        'elif sys.argv[1:2] not in (["info"],["run"]): sys.exit(99)\n')
    (bindir/'docker').chmod(0o755)
    home=tmp_path/'home';home.mkdir()
    env=dict(os.environ,HOME=str(home),PATH=str(bindir)+':'+os.environ['PATH'])
    result=subprocess.run(['python3','-c',install_script(bundle,str(root))],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    record=json.loads(result.stdout.splitlines()[-1])
    probe=subprocess.run([record['immutable_path'],'--functional-capabilities','--format','json'],env=env,capture_output=True,text=True)
    assert probe.returncode==0,probe.stderr
    assert json.loads(probe.stdout)==record['functional_runtime']
    installed_source=Path(record['immutable_path']).parent/'dingofs-integration-test'
    # Compare with the pre-transfer original using real pure framework code.
    assert (installed_source/'testcases/quota_test_cases/smoke/alias.yaml').is_symlink()
    code='''
import sys,types,logging,socket,subprocess
from pathlib import Path
def denied(*args,**kwargs): raise AssertionError('Unexpected external I/O')
socket.socket=denied
subprocess.run=denied
subprocess.Popen=denied
logger=types.ModuleType('src.config.logger')
logger.get_logger=lambda *args,**kwargs:logging.getLogger('fixture')
sys.modules['src.config.logger']=logger
sys.path.insert(0,sys.argv[1])
from src.test_runner.functional_contracts import inspect_environment
from src.test_runner.functional_plan import select_cases
original,installed=map(Path,sys.argv[2:])
selected={'quota':['testcases/quota_test_cases/smoke/alias.yaml']}
a=inspect_environment(original,'env_original',selected)
b=inspect_environment(installed,'env_original',selected)
assert not a.issues and not b.issues,(a.issues,b.issues)
assert a.source_manifest==b.source_manifest and a.digest==b.digest
assert 'testcases/quota_test_cases/case.yaml' in a.source_manifest
assert 'testcases/quota_test_cases/include.yaml' in a.source_manifest
assert 'testcases/quota_test_cases/smoke/alias.yaml' not in a.source_manifest
for root in (original,installed):
    module=root/'testcases/quota_test_cases'
    picked=select_cases({'version':1,'modules':{'quota':['smoke/alias.yaml']}},'quota',module,list(module.rglob('*.yaml')))
    assert len(picked)==1 and Path(picked[0]).resolve()==module/'case.yaml'
print('descriptor_digest_and_selection_equal')
'''
    equivalent=subprocess.run(['python3','-c',code,str(Path(wrapper_source)/'dingofs-integration-test'),str(original),str(installed_source)],env=dict(env,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True)
    assert equivalent.returncode==0,equivalent.stderr
    assert equivalent.stdout.strip()=='descriptor_digest_and_selection_equal'
    changed=Path(record['immutable_path']).parent/'dingofs-integration-test/conf/env/base.yaml'
    changed.write_text('changed base')
    probe=subprocess.run([record['immutable_path'],'--functional-capabilities','--format','json'],env=env,capture_output=True,text=True)
    assert probe.returncode!=0
