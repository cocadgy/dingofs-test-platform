"""Bounded SSH RPCs for a durable remote functional job."""
import json
from pathlib import Path
import time
from dingofs_platform.tool_packages.ssh_session import Remote

RUNNER=Path(__file__).with_name('remote_runner.py')
READER=Path(__file__).with_name('event_reader.py')


def child_bootstrap_code(payload):
    return ('REQUEST='+repr(payload)+'\nSOURCE='+repr(RUNNER.read_text())+
            '\nEVENT_SOURCE='+repr(READER.read_text())+
            "\nnamespace={'__name__':'functional_supervisor'}\nexec(compile(SOURCE,'<supervisor>','exec'),namespace)\n"
            "print(namespace['json'].dumps(namespace['bootstrap_child'](REQUEST,SOURCE,EVENT_SOURCE)))\n")


def child_snapshot_code(payload,cursor,cancel=False):
    return ('REQUEST='+repr(payload)+'\nCURSOR='+repr(cursor)+'\nCANCEL='+repr(cancel)+
            '\nSOURCE='+repr(RUNNER.read_text())+
            "\nnamespace={'__name__':'functional_supervisor'}\nexec(compile(SOURCE,'<supervisor>','exec'),namespace)\n"
            "print(namespace['json'].dumps(namespace['snapshot_child'](REQUEST,CURSOR,CANCEL)))\n")

def bootstrap_code(payload):
    return 'REQUEST='+repr(payload)+'\nSOURCE='+repr(RUNNER.read_text())+'''\nimport json,os,subprocess,sys
from pathlib import Path
secret=json.load(sys.stdin)
root=Path.home()/'.local/share/dingofs-platform/functional'/REQUEST['id']
root.mkdir(parents=True,exist_ok=True)
if not (root/'request.json').exists():
    if REQUEST.get('custom_environment'):
        name=REQUEST['env_name']
        if not name.startswith('env_platform_') or not name[13:].isalnum():raise ValueError('invalid generated environment key')
        path=root/(name+'.yaml')
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as file:file.write(secret['env_yaml'])
        redactions=root/'redactions.json'
        fd=os.open(redactions,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as file:json.dump(secret['redactions'],file)
    (root/'runner.py').write_text(SOURCE)
    (root/'state.json').write_text(json.dumps({'state':'queued','phase':'等待启动','progress':0}))
    (root/'request.json').write_text(json.dumps(REQUEST))
    with (root/'console.log').open('ab') as log:
        proc=subprocess.Popen([sys.executable,'-u',str(root/'runner.py'),str(root)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (root/'pid').write_text(str(proc.pid))
print(json.dumps({'root':str(root)}))
'''

def snapshot_code(job_id,cancel=False):
    return 'JOB='+repr(job_id)+'\nCANCEL='+repr(cancel)+'''\nimport json,os
from pathlib import Path
root=Path.home()/'.local/share/dingofs-platform/functional'/JOB
if not root.exists():print(json.dumps({'missing':True}))
else:
    if CANCEL:(root/'cancel').touch()
    value=json.loads((root/'state.json').read_text())
    if value.get('state') == 'running' or (value.get('state') == 'queued' and (root/'pid').exists()):
        try:
            pid=int((root/'pid').read_text());os.kill(pid,0)
            if str(root/'runner.py').encode() not in (Path('/proc')/str(pid)/'cmdline').read_bytes():raise ValueError('process identity mismatch')
        except (OSError,ValueError):value.update(state='unknown',error='执行器身份无法确认')
    if value.get('state') in ('success','failed','cancelled'):
        name=json.loads((root/'request.json').read_text()).get('env_name','') if (root/'request.json').exists() else ''
        if name.startswith('env_platform_'):
            (root/(name+'.yaml')).unlink(missing_ok=True)
            (root/'redactions.json').unlink(missing_ok=True)
    log=root/'console.log'
    if log.exists():
        with log.open('rb') as file:
            file.seek(max(0,log.stat().st_size-131072))
            value['log']=file.read(131072).decode(errors='replace')
    print(json.dumps(value,ensure_ascii=False))
'''

class Transport:
    def __init__(self,config):self.config=config
    def call(self,code,input_data=None):
        remote=Remote(self.config,time.monotonic()+60,lambda **kw:None,'功能测试')
        try:return remote.python(code,'任务采集',input_data=input_data,max_bytes=4*1024*1024)
        finally:remote.close()
    def start(self,payload,env_yaml=None,redactions=None):return self.call(bootstrap_code(payload),{'env_yaml':env_yaml,'redactions':redactions or []})
    def poll(self,id,cancel=False):return self.call(snapshot_code(id,cancel))
    def start_child(self,payload):return self.call(child_bootstrap_code(payload))
    def poll_child(self,payload,cursor,cancel=False):return self.call(child_snapshot_code(payload,cursor,cancel))
