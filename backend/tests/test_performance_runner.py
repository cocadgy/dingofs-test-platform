import json
import os
from pathlib import Path
import subprocess
import time
import pytest
from dingofs_platform.performance.schemas import TestSpec as BenchmarkSpec
from dingofs_platform.performance.commands import argv_for
from dingofs_platform.performance.transport import bootstrap_code
from dingofs_platform.performance import remote_runner


def fixture_job(tmp_path,mode='success',tools=('fio','elbencho')):
    home=tmp_path/'home';home.mkdir()
    install=home/'.local/share/dingofs-platform/tools/dtt/current';install.mkdir(parents=True)
    script=install/'dtt'
    script.write_text('''#!/usr/bin/env python3
import sys,json,time
from pathlib import Path
a=sys.argv[1:];get=lambda k:a[a.index(k)+1]
tool=get('-t');output=Path(get('-o'))/('performance-'+tool+'-fixture');output.mkdir(parents=True)
with (Path.home()/'invocations').open('a') as f:f.write(tool+'\\n')
print('running '+tool,flush=True)
MODE='''+repr(mode)+'''
if MODE=='timeout':time.sleep(20)
if MODE=='fail':sys.exit(7)
n=int(get('--rounds'))
report={'status':'passed','plan':{'rounds':n},'rounds':[{'status':'passed'}]*n,'statistics':{'complete':True,'requested_rounds':n,'successful_rounds':n,'metrics':{}}}
(output/'summary.json').write_text(json.dumps(report))
(output/'index.html').write_text('<html>report</html>')
''');script.chmod(0o755)
    target=tmp_path/'target';target.mkdir()
    root=home/'.local/share/dingofs-platform/performance/job';root.mkdir(parents=True)
    specs=[BenchmarkSpec(tool=t,file_size='4KiB',concurrency=1,file_count=1) for t in tools]
    request={'id':'job','target_path':str(target),'target_kind':'directory','timeout_seconds':1 if mode=='timeout' else 30,
             'tests':[{'spec':s.model_dump(),'args':argv_for(s,'__DATA__','__OUTPUT__','dtt')[1:]} for s in specs]}
    return home,root,request


def execute(tmp_path,mode='success',cancel=False):
    home,root,request=fixture_job(tmp_path,mode)
    (root/'request.json').write_text(json.dumps(request))
    if cancel:(root/'cancel').touch()
    result=subprocess.run(['python3',remote_runner.__file__,str(root)],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    state=json.loads((root/'state.json').read_text())
    assert 'reports' not in state
    state['reports']=json.loads((root/'reports.json').read_text()) if (root/'reports.json').exists() else {}
    return home,root,state


def test_multi_tool_sequential_success_and_reports(tmp_path):
    home,root,state=execute(tmp_path)
    assert state['state']=='success'
    assert (home/'invocations').read_text()=='fio\nelbencho\n'
    assert set(state['reports'])=={'fio','elbencho'}
    assert 'index.html' in state['reports']['fio']['artifacts']
    assert state['progress']==100


def test_failure_stops_later_tool(tmp_path):
    home,root,state=execute(tmp_path,'fail')
    assert state['state']=='failed'
    assert '7' in state['error']
    assert (home/'invocations').read_text()=='fio\n'


def test_cancel_before_first_tool_keeps_existing_data(tmp_path):
    home,root,state=execute(tmp_path,cancel=True)
    assert state['state']=='cancelled'
    assert not (home/'invocations').exists()


def test_timeout_stops_workload(tmp_path):
    home,root,state=execute(tmp_path,'timeout')
    assert state['state']=='failed'
    assert '超时' in state['error']
    assert (home/'invocations').read_text()=='fio\n'


def test_bootstrap_is_idempotent(tmp_path):
    home,root,request=fixture_job(tmp_path,tools=('fio',))
    env=dict(os.environ,HOME=str(home))
    for _ in range(2):
        result=subprocess.run(['python3','-c',bootstrap_code(request)],env=env,capture_output=True,text=True,timeout=5)
        assert result.returncode==0,result.stderr
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=json.loads((root/'state.json').read_text())
        if state['state'] not in ('queued','running'):break
        time.sleep(.1)
    assert state['state']=='success'
    assert (home/'invocations').read_text()=='fio\n'


def test_mount_target_rejects_unmounted_directory(tmp_path):
    home,root,request=fixture_job(tmp_path)
    request['target_kind']='mount';(root/'request.json').write_text(json.dumps(request))
    subprocess.run(['python3',remote_runner.__file__,str(root)],env=dict(os.environ,HOME=str(home)),check=True,capture_output=True)
    assert '尚未挂载' in json.loads((root/'state.json').read_text())['error']
    assert not (home/'invocations').exists()


def matrix_execute(tmp_path,mode='success',cancel=False):
    home,root,request=fixture_job(tmp_path,mode,tools=('fio','fio','elbencho'))
    for index,test in enumerate(request['tests'],1):test['id']=f'scene-{index:03d}-{test["spec"]["tool"]}'
    (root/'request.json').write_text(json.dumps(request))
    if cancel:(root/'cancel').touch()
    result=subprocess.run(['python3',remote_runner.__file__,str(root)],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    state=json.loads((root/'state.json').read_text())
    reports=json.loads((root/'reports.json').read_text()) if (root/'reports.json').exists() else {}
    return home,root,state,reports


def test_matrix_same_tool_has_independent_directories_and_reports(tmp_path):
    home,root,state,reports=matrix_execute(tmp_path)
    assert state['state']=='success'
    assert (home/'invocations').read_text()=='fio\nfio\nelbencho\n'
    assert len(reports)==3
    assert len({r['remote_path'] for r in reports.values()})==3
    assert all(r['state']=='success' and 'index.html' in r['artifacts'] for r in reports.values())
    assert all((tmp_path/'target'/'platform-performance-job'/scene).is_dir() for scene in reports)


def test_matrix_failure_continues_and_does_not_count_as_success(tmp_path):
    home,root,state,reports=matrix_execute(tmp_path,'fail')
    assert (home/'invocations').read_text()=='fio\nfio\nelbencho\n'
    assert state['state']=='failed'
    assert state['progress']==100
    assert len(reports)==3
    assert all(r['state']=='failed' for r in reports.values())


def test_matrix_cancel_marks_unexecuted_scenes(tmp_path):
    home,root,state,reports=matrix_execute(tmp_path,cancel=True)
    assert state['state']=='cancelled'
    assert len(reports)==3
    assert all(r['state']=='skipped' for r in reports.values())
    assert not (home/'invocations').exists()


def test_matrix_timeout_never_starts_later_scenes(tmp_path):
    home,root,state,reports=matrix_execute(tmp_path,'timeout')
    assert state['state']=='failed'
    assert (home/'invocations').read_text()=='fio\n'
    assert [r['state'] for r in reports.values()]==['failed','skipped','skipped']


def test_report_artifacts_respect_remaining_job_budget(tmp_path):
    output=tmp_path/'performance-fio-fixture';output.mkdir()
    (output/'summary.json').write_text('{"status":"passed"}')
    (output/'index.html').write_text('x'*1000)
    report,artifacts=remote_runner.report_files(tmp_path,'fio',budget=100)
    assert report['status']=='passed'
    assert 'summary.json' in artifacts
    assert 'index.html' not in artifacts


@pytest.mark.parametrize('mode,enabled,removed',[('success',True,True),('success',False,False),('fail',True,False),('cancel',True,False)])
def test_optional_cleanup_only_successful_task_data(tmp_path,mode,enabled,removed):
    home,root,request=fixture_job(tmp_path,mode,tools=('fio',))
    request['cleanup_data']=enabled
    if mode=='cancel':(root/'cancel').touch()
    sentinel=tmp_path/'target'/'keep.txt';sentinel.write_text('original')
    (root/'request.json').write_text(json.dumps(request))
    subprocess.run(['python3',remote_runner.__file__,str(root)],env=dict(os.environ,HOME=str(home)),check=True,capture_output=True,timeout=30)
    task_data=tmp_path/'target'/'platform-performance-job'
    assert task_data.exists()!=removed
    assert sentinel.read_text()=='original'
    reports=json.loads((root/'reports.json').read_text())
    if mode=='success':
        assert 'index.html' in reports['fio']['artifacts']
        assert (root/'output'/'fio').exists()


def test_cleanup_refuses_changed_directory_identity(tmp_path):
    data=tmp_path/'task';data.mkdir();(data/'keep').write_text('original')
    identity=data.stat()
    with pytest.raises(RuntimeError,match='身份已变化'):
        remote_runner.cleanup_task_data(data,(identity.st_dev,identity.st_ino+1),5)
    assert (data/'keep').read_text()=='original'


def test_cleanup_does_not_follow_child_symlinks(tmp_path):
    outside=tmp_path/'original';outside.mkdir();(outside/'keep').write_text('original')
    data=tmp_path/'task';data.mkdir();(data/'link').symlink_to(outside,target_is_directory=True)
    identity=data.stat();remote_runner.cleanup_task_data(data,(identity.st_dev,identity.st_ino),5)
    assert not data.exists()
    assert (outside/'keep').read_text()=='original'
