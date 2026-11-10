"""Standalone, task-owned remote functional test supervisor."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
import fcntl
import importlib.util
import re

def save(path,value):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream,ensure_ascii=False)
        stream.flush();os.fsync(stream.fileno())
    temp.replace(path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def process_identity(pid):
    return (Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]


def child_root(request):
    for key in ('parent_id','child_id','launch_token'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request[key]):
            raise ValueError('invalid child identity')
    return Path.home()/'.local/share/dingofs-platform/functional-v2'/request['parent_id']/'supervisor'/request['child_id']


def bootstrap_child(request,source,event_source):
    root=child_root(request)
    os.umask(0o077)
    root.mkdir(parents=True,exist_ok=True)
    with (root/'bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (root/'request.json').exists():
            if json.loads((root/'request.json').read_text())!=request:
                raise ValueError('child request differs')
            return {'root':str(root)}
        (root/'runner.py').write_text(source)
        # Remote hosts support Python 3.9; postpone the reviewed reader's modern
        # type annotations without changing its parser or cursor semantics.
        (root/'event_reader.py').write_text('from __future__ import annotations\n'+event_source)
        save(root/'state.json',{'state':'unknown'})
        # The durable request is a one-shot launch claim, including crashes
        # between this write and Popen. There is no implicit bootstrap retry.
        save(root/'request.json',request)
        with (root/'supervisor.log').open('ab') as log:
            subprocess.Popen([sys.executable,'-I','-B','-u',str(root/'runner.py'),str(root)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    return {'root':str(root)}


def event_reader(root):
    spec=importlib.util.spec_from_file_location('_functional_event_reader',root/'event_reader.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


def child_output(root,request):
    return root.parent.parent/'output'/request['parent_id']/request['child_id']


def forward_cancel(root,output):
    # Opening the output before the wrapper's empty-directory check would
    # reject a valid launch. The first producer event proves that check passed.
    if (root/'cancel').exists() and (output/'functional-events.jsonl').exists():
        fd=os.open(output/'functional-cancel',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)


def snapshot_child(request,cursor,cancel=False):
    from dataclasses import asdict
    root=child_root(request)
    if not (root/'request.json').exists():return {'missing':True,'cursor_before':cursor}
    if json.loads((root/'request.json').read_text())!=request:raise ValueError('child request differs')
    output=child_output(root,request)
    if cancel:
        (root/'cancel').touch()
        forward_cancel(root,output)
    value=json.loads((root/'state.json').read_text())
    value.update(root=str(root),output=str(output))
    value['cursor_before']=cursor
    process=value.get('process')
    if process and process['state']=='running':
        try:
            if process_identity(process['pid'])!=process['start_time']:raise ValueError('reused pid')
        except (OSError,ValueError,IndexError):
            value['process']={**process,'state':'unknown'}
            value['state']='unknown'
    reader=event_reader(root)
    path=output/'functional-events.jsonl'
    if path.exists() or cursor:
        try:
            limit=1000
            while True:
                batch=reader.read_events(path,cursor.get('offset',0),file_identity=cursor.get('file_identity'),
                    last_event=cursor.get('last_event'),max_events=limit)
                wire=asdict(batch)
                if len(json.dumps(wire).encode())<=3*1024*1024:break
                if limit==1:raise ValueError('event exceeds RPC limit')
                limit=max(1,limit//2)
            value['event_batch']=wire
            value['has_more']=not batch.partial_tail and path.stat().st_size>batch.new_offset
        except reader.EventReadError as exc:
            value['protocol_error']=exc.code
    report=value.get('report_path')
    if report:
        target=output/report
        rel=Path(report)
        if (not rel.is_absolute() and '..' not in rel.parts and target.is_file()
                and target.name=='index.html' and target.resolve().is_relative_to(output.resolve())
                and not any(p.is_symlink() for p in [target,*target.parents] if p!=output.parent)):
            value['verified_report']={'child_id':request['child_id'],'html_path':report}
    log=root/'console.log'
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0,log.stat().st_size-131072))
            value['log']=stream.read(131072).decode(errors='replace')
    return value


def run_child(root,request):
    output=child_output(root,request)
    pinned=Path(request['immutable_path'])
    if not pinned.is_absolute() or '..' in pinned.parts or {'current','latest'}&set(pinned.parts):
        raise ValueError('immutable runtime required')
    save(root/'plan.json',{'version':1,'modules':{request['module']:request['cases']},
                          'hashes':{request['module']:request['hashes']}})
    save(root/'context.json',request['context'])
    args=[str(pinned),'-t','int','-s',request['module'],'--env',request['env_name'],
          '--case-plan',str(root/'plan.json'),'--functional-context',str(root/'context.json'),
          '-o',str(root.parent.parent/'output')]
    if (root/'cancel').exists():
        save(root/'state.json',{'state':'cancelled','zero_start':{'child_id':request['child_id'],
             'launch_token':request['launch_token']}})
        return
    with (root/'console.log').open('ab',buffering=0) as log:
        process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                 start_new_session=True)
        identity={'child_id':request['child_id'],'launch_token':request['launch_token'],
                  'pid':process.pid,'start_time':process_identity(process.pid),
                  'started_at':datetime.now(timezone.utc).isoformat(),'state':'running'}
        state={'state':'running','process':identity}
        save(root/'state.json',state)
        while process.poll() is None:
            forward_cancel(root,output)
            time.sleep(0.2)
        rc=process.wait()
    identity={**identity,'state':'exited'}
    proof={key:identity[key] for key in ('child_id','launch_token','pid','start_time')}
    proof['returncode']=rc
    state={'state':'exited','process':identity,'returncode':rc,'end_proof':proof}
    resources={}
    path=output/'functional-events.jsonl'
    if path.exists():
        reader=event_reader(root)
        cursor={}
        try:
            while True:
                batch=reader.read_events(path,cursor.get('offset',0),file_identity=cursor.get('file_identity'),
                                        last_event=cursor.get('last_event'))
                for item in batch.events:
                    if item['type']=='resource_changed':
                        resource=item['data']['resource']
                        resources[resource['id']]=resource
                    if item['type']=='report_finished' and item['data'].get('success'):
                        state['report_path']=item['data']['path']
                if batch.partial_tail:
                    state['protocol_error']='incomplete terminal event line'
                    break
                if batch.new_offset==cursor.get('offset',0):break
                cursor={'offset':batch.new_offset,'file_identity':batch.file_identity,'last_event':batch.last_event}
        except reader.EventReadError as exc:state['protocol_error']=exc.code
    # The journal write precedes its event. Independently compare every final
    # resource with the task-owned journal so a lost event can never hide it.
    journal={}
    try:
        path=output/'resources.jsonl'
        if path.exists():
            with path.open('rb') as stream:
                while True:
                    line=stream.readline(1024*1024+1)
                    if not line:break
                    if len(line)>1024*1024 or not line.endswith(b'\n'):raise ValueError('invalid journal')
                    record=json.loads(line)
                    journal[record['id']]=record
        state['journal_verified']=journal==resources
    except (OSError,ValueError,KeyError,TypeError):
        state['journal_verified']=False
    if not state['journal_verified']:state['protocol_error']='resource_journal_mismatch'
    save(root/'state.json',state)

def run_body(root):
    request=json.loads((root/'request.json').read_text());output=root/'output';output.mkdir(exist_ok=True)
    states=root/'state.json';logpath=root/'console.log';started=time.monotonic()
    state=dict(state='running',phase='准备测试',progress=0,completed=0,total=sum(map(len,request['selected'].values())),error='',reports={})
    save(states,state)
    dtt=Path.home()/'.local/share/dingofs-platform/tools/dtt/current/dtt'
    if not dtt.is_file():dtt=shutil.which('dtt') or Path.home()/'.local/bin/dtt'
    if not Path(dtt).is_file():raise RuntimeError('未部署 dtt，请先在工具包管理更新')
    plan={'version':1,'modules':{('large_scale' if key=='large_scale_cache' else key):paths for key,paths in request['selected'].items()},
          'hashes':{('large_scale' if key=='large_scale_cache' else key):hashes for key,hashes in request['hashes'].items()}}
    (root/'plan.json').write_text(json.dumps(plan))
    modules=list(plan['modules'])
    args=[str(dtt),'-t','int','-s',','.join(modules),'--env',request['env_name'],
          '--case-plan',str(root/'plan.json'),'-m',str(root/'data'),'-o',str(output)]
    if request.get('custom_environment'):
        if not (root/(request['env_name']+'.yaml')).is_file():raise RuntimeError('自建环境文件未准备好')
        args+=['--int-env-file',str(root/(request['env_name']+'.yaml'))]
    (root/'data').mkdir(exist_ok=True)
    env=os.environ.copy();env['DTT_MDSADDR']=request['mds_addr']
    if request.get('source_file'):
        env['DTT_INT_SOURCE_FILE']=request['source_file']
        env['DTT_INT_SOURCE_SHA256']=request['source_file_sha']
        env['DTT_INT_STORAGE_SHA256']=request['storage_file_sha']
    env['DTT_INT_RERUNS']=str(request['retries'])
    if request.get('fs_mode')=='existing':
        env['DTT_INT_EXISTING_FS']='true'
    else:
        env.pop('DTT_INT_EXISTING_FS',None)
    for kind,name in [('dingo-client','DTT_CLIENT_BINARY'),('dingo-cache','DTT_CACHE_BINARY'),('dingo-mds-client','DTT_MDS_CLIENT_BINARY')]:
        env.pop(name,None)
        if request.get('binaries',{}).get(kind):env[name]=request['binaries'][kind]
    if (root/'cancel').exists():
        state.update(state='cancelled',phase='已停止',progress=100)
        save(states,state);return
    print('$ '+shlex.join(args),flush=True)
    redactions=json.loads((root/'redactions.json').read_text()) if (root/'redactions.json').exists() else []
    with logpath.open('ab',buffering=0) as log:
        for kind,path in request.get('binaries',{}).items():
            if path:log.write(('Selected binary: '+kind+'='+path+'\n').encode())
        process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,env=env,start_new_session=True)
        def copy_output():
            for line in process.stdout:
                text=line.decode(errors='replace')
                for secret in redactions:
                    if secret:text=text.replace(secret,'[REDACTED]')
                log.write(text.encode())
        reader=threading.Thread(target=copy_output,daemon=True);reader.start()
        while process.poll() is None:
            if (root/'cancel').exists() or time.monotonic()-started>request['timeout_seconds']:
                (root/'cancel').touch()
                (output/'functional-cancel').touch()
                state['phase']='正在停止：等待当前用例结束并清理'
            events=output/'functional-events.jsonl'
            if events.exists():
                rows=[]
                for line in events.read_text(errors='replace').splitlines()[-10000:]:
                    try:rows.append(json.loads(line))
                    except ValueError:pass
                finished={(e.get('module'),e.get('case')):e for e in rows if e.get('type')=='case_finished'}
                state['completed']=min(len(finished),state['total'])
                state['progress']=int(90*state['completed']/max(1,state['total']))
                running=next((e for e in reversed(rows) if e.get('type')=='case_started'),None)
                if running and not (root/'cancel').exists():state['phase']='执行 '+running.get('module','')+'/'+running.get('case','')
                state['result']={'cases':list(finished.values()),'events':rows[-1000:]}
            save(states,state);time.sleep(1)
        reader.join(timeout=5)
        rc=process.returncode
    events=output/'functional-events.jsonl'
    if events.exists():
        rows=[]
        for line in events.read_text(errors='replace').splitlines()[-10000:]:
            try:rows.append(json.loads(line))
            except ValueError:pass
        finished={(e.get('module'),e.get('case')):e for e in rows if e.get('type')=='case_finished'}
        state['completed']=min(len(finished),state['total'])
        state['result']={'cases':list(finished.values()),'events':rows[-1000:]}
    state['progress']=100
    result=state.get('result',{})
    cases=result.get('cases',[])
    expected={(module,path) for module,paths in plan['modules'].items() for path in paths}
    completed={(case.get('module'),case.get('case')) for case in cases}
    failure=''
    if rc:failure='dtt 退出码 '+str(rc)
    elif any(event.get('suite_errors',0) for event in result.get('events',[]) if event.get('type')=='suite_finished'):
        failure='测试套件执行失败，请查看日志'
    elif any(case.get('status') in ('FAIL','ERROR') for case in cases):failure='测试用例失败，请查看报告'
    elif completed != expected:failure='用例结果不完整：预期 '+str(len(expected))+'，收到 '+str(len(completed))
    if (root/'cancel').exists():state.update(state='cancelled',phase='已停止')
    elif failure:state.update(state='failed',phase='测试失败',error=failure)
    else:state.update(state='success',phase='已完成')
    state['result']={**state.get('result',{}),'returncode':rc}
    save(states,state)

def run(root):
    request=json.loads((root/'request.json').read_text())
    if request.get('version')==2:
        with (root/'runner.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if (root/'launch.json').exists():return
            save(root/'launch.json',{'child_id':request['child_id'],'launch_token':request['launch_token']})
            return run_child(root,request)
    try:
        run_body(root)
    finally:
        request_path=root/'request.json'
        if request_path.exists():
            name=json.loads(request_path.read_text()).get('env_name','')
            if name.startswith('env_platform_'):
                try:
                    (root/(name+'.yaml')).unlink(missing_ok=True)
                    (root/'redactions.json').unlink(missing_ok=True)
                except OSError as exc:
                    state_path=root/'state.json'
                    state=json.loads(state_path.read_text()) if state_path.exists() else {}
                    state.update(state='failed',phase='临时环境清理失败',error='明文环境文件清理失败：'+str(root/(name+'.yaml')))
                    save(state_path,state)
                    raise RuntimeError(state['error']) from exc

if __name__=='__main__':
    root=Path(sys.argv[1])
    try:run(root)
    except Exception as exc:
        save(root/'state.json',dict(state='failed',phase='执行失败',progress=0,error=str(exc),result={}))
        raise
