"""Bounded RPCs; the remote supervisor survives API and browser restarts."""
import json
from pathlib import Path
import time
from dingofs_platform.tool_packages.ssh_session import Remote


class StartNotDispatched(ConnectionError):
    """Connection setup failed before any remote bootstrap could be sent."""


def bootstrap_code():
    runner=Path(__file__).with_name('remote_runner.py').read_text()
    return 'RUNNER='+repr(runner)+'''\nimport fcntl,json,os,subprocess,sys
from pathlib import Path
REQUEST=json.load(sys.stdin)
root=Path.home()/'.local/share/dingofs-platform/performance'/REQUEST['id']
root.mkdir(parents=True,exist_ok=True)
with (root/'bootstrap.lock').open('w') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if (root/'cancel').exists() and not (root/'request.json').exists():
        (root/'state.json').write_text(json.dumps({'state':'cancelled','phase':'启动前已取消','progress':100}))
    elif not (root/'request.json').exists():
        (root/'runner.py').write_text(RUNNER)
        (root/'state.json').write_text(json.dumps({'state':'queued','phase':'等待远端启动','progress':0}))
        # Once request.json exists, never automatically launch this job again.
        (root/'request.json').write_text(json.dumps(REQUEST))
        with (root/'console.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,'-u',str(root/'runner.py'),str(root)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        (root/'pid').write_text(str(process.pid))
print(json.dumps({'root':str(root)}))
'''


def snapshot_code(job_id,cancel=False):
    return 'JOB_ID='+repr(job_id)+'\nCANCEL='+repr(cancel)+'''\nimport fcntl,json,os
from pathlib import Path
root=Path.home()/'.local/share/dingofs-platform/performance'/JOB_ID
if CANCEL:
    # Serialize with bootstrap and persist the fence even when the initial SSH
    # call never arrived. A delayed bootstrap can no longer launch this ID.
    root.mkdir(parents=True,exist_ok=True)
    with (root/'bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        (root/'cancel').touch()
        if not (root/'request.json').exists():
            (root/'state.json').write_text(json.dumps({'state':'cancelled','phase':'启动前已取消','progress':100}))
if not root.exists():
    print(json.dumps({'missing':True}))
else:
    state=json.loads((root/'state.json').read_text())
    if state.get('state') in ('queued','running'):
        try:
            pid=int((root/'pid').read_text());os.kill(pid,0)
            if str(root/'runner.py').encode() not in (Path('/proc')/str(pid)/'cmdline').read_bytes():
                raise ValueError('监督进程身份已变化')
        except (OSError,ValueError):state.update(state='unknown',error='远端监督进程不在运行，执行结果尚未确认')
    # Do not send HTML reports on each poll; transfer them once after completion.
    if state.get('state') in ('queued','running'):state.pop('reports',None)
    elif (root/'reports.json').exists():state['reports']=json.loads((root/'reports.json').read_text())
    log=root/'console.log'
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0,log.stat().st_size-131072))
            state['log']=stream.read(131072).decode(errors='replace')
    print(json.dumps(state,ensure_ascii=False))
'''


class Transport:
    def __init__(self,config):self.config=config

    def call(self,code,input_data=None,*,starting=False):
        # Reports may be larger than the default tool RPC envelope.
        try:
            remote=Remote(self.config,time.monotonic()+60,lambda **kw:None,'性能测试')
        except Exception as exc:
            if starting:
                raise StartNotDispatched('SSH 连接失败，未下发测试启动命令：'+str(exc)) from exc
            raise
        try:return remote.python(code,'性能任务采集',input_data=input_data,max_bytes=40*1024*1024)
        finally:remote.close()

    def start(self,payload):return self.call(bootstrap_code(),payload,starting=True)
    def poll(self,id,cancel=False):return self.call(snapshot_code(id,cancel))
