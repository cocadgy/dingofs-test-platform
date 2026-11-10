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

def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False));temp.replace(path)

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
