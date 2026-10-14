import pytest
from dingofs_platform.tool_packages.automatic import choose_image, DTT_IMAGE


def test_scp_success_never_pulls_on_target():
    calls=[]
    result=choose_image(lambda:{'image_id':'local'},lambda:calls.append('pull'))
    assert result['method']=='platform-transfer'
    assert calls==[]


def test_scp_failure_pulls_and_preserves_reason():
    def broken():raise RuntimeError('scp failed')
    result=choose_image(broken,lambda:{'success':True,'image_id':'remote'})
    assert result['method']=='registry'
    assert result['transfer_error']=='scp failed'


def test_both_paths_fail():
    def broken():raise RuntimeError('scp failed')
    with pytest.raises(RuntimeError,match='pull failed'):
        choose_image(broken,lambda:{'success':False,'error':'pull failed'})


@pytest.mark.parametrize('scp_ok',[True,False])
def test_complete_automatic_flow_with_isolated_hosts(tmp_path,monkeypatch,scp_ok):
    import os,subprocess,json
    from pathlib import Path
    from dingofs_platform.tool_packages import automatic
    source=tmp_path/'source';target=tmp_path/'target'
    source.mkdir();target.mkdir()
    directory=source/'tools';directory.mkdir()
    (directory/'dingofs-testsuite-tool').write_text('#!/bin/sh\nif [ "$1" = config ]; then printf "image: "; cat "$DINGOFS_TESTSUITE_CONFIG_DIR/image"; printf "runtime: "; cat "$DINGOFS_TESTSUITE_CONFIG_DIR/runtime"; else echo dtt; fi\n')
    for name in ('dtt-ai-analyze','analysis.schema.json'):(directory/name).write_text('fixture')
    (directory/'scripts').mkdir()
    (directory/'entrypoint.sh').write_text('#!/bin/bash\n')
    for name in ('performance_benchmark.py','performance_plan.py','performance_report.py','performance_tools.py','ai_storage_scenarios.py'):
        (directory/'scripts'/name).write_text('# fixture runtime\n')
    image='sha256:'+'a'*64
    for home in (source,target):
        bindir=home/'bin';bindir.mkdir()
        # Fake only the container runtime. Remote Python helpers and file copying run normally.
        docker='#!/bin/sh\necho "$*" >> "$HOME/commands"\ncase "$1" in\npull) '+'exit 0'+';;\nimage) echo "'+image+' amd64";;\nsave) printf fixture > "$3";;\nesac\n'
        (bindir/'docker').write_text(docker);(bindir/'docker').chmod(0o755)
    class File:
        def __init__(self,path,mode):self.file=open(path,mode)
        def __enter__(self):return self
        def __exit__(self,*args):self.file.close()
        def read(self,n):return self.file.read(n)
        def write(self,data):return self.file.write(data)
        def prefetch(self,*args,**kwargs):pass
        def set_pipelined(self,*args):pass
    class Sftp:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def open(self,path,mode):return File(path,mode)
        def remove(self,path):os.unlink(path)
    phases=[]
    class LocalRemote:
        def __init__(self,config,deadline,report,label):self.home=config.home;self.report=report
        def python(self,code,phase,input_data=None,progress_range=None):
            if input_data is not None:
                import shutil
                if not scp_ok:
                    raise RuntimeError('SCP unavailable')
                shutil.copyfile(input_data["source"],input_data["destination"])
                return {"success":True}
            phases.append((self.home,phase))
            env=dict(os.environ,HOME=str(self.home),PATH=str(self.home/'bin')+':/usr/local/bin:/usr/bin:/bin')
            result=subprocess.run(['python3','-c',code],env=env,capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])
        def sftp(self):return Sftp()
        def remaining(self):return 1800
        def close(self):pass
    monkeypatch.setattr(automatic,'Remote',LocalRemote)
    from types import SimpleNamespace
    target_config=SimpleNamespace(home=target,host='target',port=22,username='user',password='secret')
    source_config=SimpleNamespace(home=source)
    result=automatic.deploy(target_config,source_config,{'tool':'dtt','directory':str(directory),'image':DTT_IMAGE,'allow_cached':False},30,lambda **kw:None)
    assert result['method']==('platform-transfer' if scp_ok else 'registry')
    assert result['image_id']==image
    installed=target/'.local/share/dingofs-platform/tools/dtt/current'
    assert (installed/'dtt').is_file()
    assert 'DTT_PERFORMANCE_RUNTIME_DIR' in (installed/'dtt').read_text()
    assert (installed/'performance_plan.py').is_file()
    assert (installed/'ai_storage_scenarios.py').is_file()
    source_commands=(source/'commands').read_text() if (source/'commands').exists() else ''
    assert 'save -o' in source_commands
    target_commands=(target/'commands').read_text()
    assert ('pull ' in target_commands)==(not scp_ok)
    assert list((source/'.local/share/dingofs-platform/exports').iterdir())==[]


def test_pull_helper_uses_ten_minute_timeout(monkeypatch):
    import json,subprocess,platform
    from dingofs_platform.tool_packages.automatic import helper
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs['timeout']))
        output=b'sha256:test '+({'x86_64':'amd64','aarch64':'arm64'}.get(platform.machine(),platform.machine())).encode() if 'inspect' in argv else b'ok'
        return subprocess.CompletedProcess(argv,0,output)
    monkeypatch.setattr(subprocess,'run',run)
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    exec(helper({'operation':'pull','image':DTT_IMAGE}),{})
    assert next(timeout for argv,timeout in calls if 'pull' in argv)==600
