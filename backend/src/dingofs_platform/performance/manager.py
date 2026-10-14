from .mdtest import custom_script
"""Collect durable remote jobs; never restart a workload after an unknown outcome."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import threading
from sqlalchemy import select
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from .models import PerformanceRun,ACTIVE
from .commands import argv_for
from .schemas import TestSpec
from .transport import Transport


def now():return datetime.now(timezone.utc)


class PerformanceManager:
    def __init__(self,app):
        self.app=app
        self.stop_event=threading.Event()
        self.pool=None
        self.thread=None
        self.running={}

    def start(self):
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='performance')
        self.thread=threading.Thread(target=self.loop,daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(3)
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.running={id:f for id,f in self.running.items() if not f.done()}
                with self.app.state.session_factory() as db:
                    ids=list(db.scalars(select(PerformanceRun.id).where(PerformanceRun.state.in_(ACTIVE)).order_by(PerformanceRun.updated_at)))
                for id in ids:
                    if len(self.running)>=4:break
                    if id not in self.running:self.running[id]=self.pool.submit(self.process,id)
            except Exception:
                __import__('logging').getLogger(__name__).exception('performance monitor failed')
            self.stop_event.wait(2)

    def process(self,id):
        factory=self.app.state.session_factory
        password=''
        try:
            with factory.begin() as db:
                row=db.get(PerformanceRun,id,with_for_update=True)
                if not row or row.state not in ACTIVE:return
                machine=db.get(Machine,row.machine_id)
                snapshot=row.snapshot
                if [machine.address,machine.ssh_port,machine.ssh_user]!=snapshot['connection']:
                    raise RuntimeError('机器连接信息已改变，无法确认原测试状态')
                password=decrypt_password(machine.ssh_password_ciphertext,self.app.state.settings.credential_encryption_key)
                config=SSHConfig(machine.address,machine.ssh_port,machine.ssh_user,password)
                launch=row.state=='queued'
                if launch and row.cancel_requested:
                    row.state='cancelled';row.phase='启动前已取消';row.finished_at=now();return
                if launch and now()>=row.deadline:
                    row.state='failed';row.error='排队期间已超过任务总超时';row.finished_at=now();return
                if launch:row.state='running';row.phase='启动远端任务'
                deadline=row.deadline
            transport=getattr(self.app.state,'performance_transport',Transport)(config)
            if launch:
                specs=[TestSpec(**t) for t in snapshot['tests']]
                payload={'id':id,'target_path':snapshot['target_path'],'target_kind':snapshot['target_kind'],
                         'timeout_seconds':max(1,int((deadline-now()).total_seconds())),
                         'cleanup_data':snapshot.get('cleanup_data',False),
                         'tests':[{'id':snapshot['scenarios'][i]['id'] if snapshot.get('scenarios') else t.tool,'spec':t.model_dump(),'custom_script':custom_script(t) if t.tool=='mdtest' else None,'args':argv_for(t,'__DATA__','__OUTPUT__','dtt')[1:]} for i,t in enumerate(specs)]}
                root=transport.start(payload)['root']
                with factory.begin() as db:db.get(PerformanceRun,id).remote_root=root
            while not self.stop_event.is_set():
                with factory() as db:
                    row=db.get(PerformanceRun,id)
                    cancel=row.cancel_requested or now()>row.deadline
                result=transport.poll(id,cancel)
                if result.get('missing'):raise RuntimeError('远端任务记录不存在，结果未确认；不会自动重新执行')
                with factory.begin() as db:
                    row=db.get(PerformanceRun,id,with_for_update=True)
                    state=result.get('state')
                    if state not in ('queued','running','success','failed','cancelled','unknown'):raise RuntimeError('远端任务状态格式错误')
                    row.state=('cancelling' if row.cancel_requested else 'running') if state in ('queued','running') else state
                    row.phase=result.get('phase','正在执行')[:160]
                    row.progress=min(100,max(0,int(result.get('progress',0))))
                    row.log=result.get('log','')[-131072:]
                    row.error=result.get('error','')[:16000]
                    if 'reports' in result:row.reports=result['reports']
                    elif 'scene_results' in result:row.reports=result['scene_results']
                    if state not in ('queued','running','unknown'):row.finished_at=now()
                if state not in ('queued','running'):return
                self.stop_event.wait(2)
        except Exception as exc:
            with factory.begin() as db:
                row=db.get(PerformanceRun,id)
                if row and row.state in ACTIVE:
                    row.state='unknown'
                    message=str(exc)
                    if password:message=message.replace(password,'[REDACTED]')
                    row.error='状态采集失败，正在重试；不会重复启动测试。'+message[:2000]
