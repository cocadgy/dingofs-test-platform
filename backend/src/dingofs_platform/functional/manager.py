"""Durable polling worker. Unknown remote outcomes are never relaunched."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import logging
import json
import shlex
import threading
from sqlalchemy import select
from dingofs_platform.inventory.models import Machine
from dingofs_platform.storage.service import resolve as resolve_storage
from .environments.render import render_environment
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from .models import FunctionalRun,ACTIVE
from .transport import Transport
from dingofs_platform.operations.leases import (legacy_functional_requests, ensure_leases, lock_keys,
    release_verified, completion_evidence)

def now():return datetime.now(timezone.utc)

def redact(value,secrets):
    if isinstance(value,dict):return {key:redact(item,secrets) for key,item in value.items()}
    if isinstance(value,list):return [redact(item,secrets) for item in value]
    if not isinstance(value,str):return value
    for secret in secrets:
        if secret:
            value=value.replace(secret,'[REDACTED]').replace(shlex.quote(secret),'[REDACTED]')
    return value

class FunctionalManager:
    def __init__(self,app):
        self.app=app;self.stop_event=threading.Event();self.pool=None;self.thread=None;self.running={}
    def start(self):
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='functional')
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(3)
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)
    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.running={id:f for id,f in self.running.items() if not f.done()}
                with self.app.state.session_factory() as db:
                    ids=list(db.scalars(select(FunctionalRun.id).where(FunctionalRun.version==1,FunctionalRun.state.in_(ACTIVE)).order_by(FunctionalRun.updated_at)))
                for id in ids:
                    if len(self.running)>=4:break
                    if id not in self.running:self.running[id]=self.pool.submit(self.process,id)
            except Exception:logging.getLogger(__name__).exception('functional monitor failed')
            self.stop_event.wait(2)
    def process(self,id):
        factory=self.app.state.session_factory;password='';secrets=[];remote_attempted=False
        requests=[];owner='functional:'+id
        try:
            with factory.begin() as db:
                row=db.get(FunctionalRun,id)
                if not row or row.version!=1 or row.state not in ACTIVE:return
                remote_attempted=row.state!='queued'
                requests=legacy_functional_requests(db,row.cluster_id,row.machine_id,row.snapshot,
                    self.app.state.settings.functional_source_root)
                lock_keys(db,requests)
                row=db.get(FunctionalRun,id,with_for_update=True,populate_existing=True)
                if row.version!=1 or row.state not in ACTIVE:return
                # A resumed job may still be running remotely, even if polling fails.
                remote_attempted=row.state!='queued'
                machine=db.get(Machine,row.machine_id);snapshot=row.snapshot
                if [machine.address,machine.ssh_port,machine.ssh_user]!=snapshot['connection']:
                    raise RuntimeError('机器连接信息已改变，不能确认测试状态')
                password=decrypt_password(machine.ssh_password_ciphertext,self.app.state.settings.credential_encryption_key)
                config=SSHConfig(machine.address,machine.ssh_port,machine.ssh_user,password)
                launch=row.state=='queued'
                if launch and row.cancel_requested:
                    row.state='cancelled';row.phase='启动前已取消';row.finished_at=now();return
                if launch and now()>=row.deadline:
                    row.state='failed';row.error='排队超时';row.finished_at=now();return
                if not ensure_leases(db,owner,requests).acquired:
                    row.phase='等待目标资源释放';return
                if launch:
                    legacy_functional_requests(db,row.cluster_id,row.machine_id,row.snapshot,
                        self.app.state.settings.functional_source_root,strict=True)
                if launch:row.state='running';row.phase='启动远端任务'
                deadline=row.deadline
                env_yaml=None
                profile_snapshot=snapshot.get('environment_profile_snapshot')
                if launch and profile_snapshot and profile_snapshot['kind']=='custom':
                    client_machine=db.get(Machine,profile_snapshot['machine_id'])
                    if not client_machine or [client_machine.address,client_machine.ssh_port,client_machine.ssh_user]!=profile_snapshot['client_connection']:
                        raise RuntimeError('测试机连接信息已改变，请重新提交任务')
                    if not client_machine.ssh_password_ciphertext:
                        raise RuntimeError('测试机没有配置 SSH 密码')
                    ssh_password=decrypt_password(client_machine.ssh_password_ciphertext,self.app.state.settings.credential_encryption_key)
                    machine_hosts={}
                    for member_id,connection in profile_snapshot.get('member_connections',{}).items():
                        member=db.get(Machine,member_id)
                        if not member or [member.address,member.ssh_port,member.ssh_user]!=connection:
                            raise RuntimeError('客户端或缓存机器连接信息已改变，请重新提交任务')
                        member_password=decrypt_password(member.ssh_password_ciphertext,self.app.state.settings.credential_encryption_key)
                        if member.ssh_user!=client_machine.ssh_user or member_password!=ssh_password:
                            raise RuntimeError('当前测试工具要求所有客户端和缓存机器使用同一 SSH 用户及密码')
                        machine_hosts[member_id]=member.address
                    storage,_=resolve_storage(db,profile_snapshot['storage_profile_id'],profile_snapshot['storage_profile_revision'],self.app.state.settings.credential_encryption_key)
                    settings=json.loads(json.dumps(profile_snapshot['settings']).replace('__TASK_ID__',id))
                    frozen={'environment_key':snapshot['env_name'],'mds_addr':snapshot['mds_addr'],
                            'client_host':client_machine.address,'ssh_user':client_machine.ssh_user,
                            'machine_id':profile_snapshot['machine_id'],'machine_hosts':machine_hosts,
                            'settings':settings,
                            'dingo_tool_path':profile_snapshot['dingo_tool_path']}
                    env_yaml=render_environment(frozen,storage,ssh_password)
                    secrets=[ssh_password,*[v for k,v in storage.items() if k in ('s3_ak','s3_sk','rados_key')]]
            transport=getattr(self.app.state,'functional_transport',Transport)(config)
            if launch:
                payload={'id':id,**{k:snapshot[k] for k in ('selected','env_name','mds_addr','retries','binaries','hashes')},
                         'timeout_seconds':max(1,int((deadline-now()).total_seconds())),
                         'fs_mode':snapshot.get('fs_mode','auto')}
                payload['custom_environment']=env_yaml is not None
                if profile_snapshot and profile_snapshot['kind']=='predefined':
                    payload['source_file']=profile_snapshot['source_file']
                    payload['source_file_sha']=profile_snapshot['source_file_sha']
                    payload['storage_file_sha']=profile_snapshot['storage_file_sha']
                remote_attempted=True
                root=(transport.start(payload,env_yaml,secrets) if env_yaml is not None else transport.start(payload))['root']
                with factory.begin() as db:db.get(FunctionalRun,id).remote_root=root
            while not self.stop_event.is_set():
                with factory() as db:
                    row=db.get(FunctionalRun,id);cancel=row.cancel_requested or now()>row.deadline
                result=transport.poll(id,cancel)
                if result.get('missing'):raise RuntimeError('远端任务记录不存在，结果未确认')
                with factory.begin() as db:
                    lock_keys(db,requests)
                    row=db.get(FunctionalRun,id,with_for_update=True)
                    state=result.get('state')
                    if state not in ('queued','running','success','failed','cancelled','unknown'):
                        raise RuntimeError('远端状态格式错误')
                    row.state=('cancelling' if row.cancel_requested else 'running') if state in ('queued','running') else state
                    row.phase=result.get('phase','正在执行')[:160]
                    row.progress=min(100,max(0,int(result.get('progress',0))))
                    row.log=redact(result.get('log','')[-131072:],secrets)
                    row.error=redact(result.get('error','')[:16000],secrets)
                    if 'result' in result:row.result=redact(result['result'],secrets)
                    if state not in ('queued','running','unknown'):
                        row.finished_at=now()
                        row.state='needs_attention'
                        row.phase='远端任务已结束，等待资源复核'
                        row.error=(row.error+'\n旧任务缺少恢复及资源清理证据，占用将保留至人工复核。').strip()
                if state not in ('queued','running'):
                    if state=='unknown':self.stop_event.wait(5)
                    else:return
                self.stop_event.wait(2)
        except Exception as exc:
            with factory.begin() as db:
                lock_keys(db,requests)
                row=db.get(FunctionalRun,id)
                if row and row.state in ACTIVE:
                    row.state='unknown' if remote_attempted else 'failed'
                    row.error=('状态采集失败，正在重试；不会重复启动。' if remote_attempted else '启动前验证失败。')+redact(str(exc)[:2000],[password,*secrets])
                    if not remote_attempted:
                        row.finished_at=now()
                        release_verified(db,owner,completion_evidence(owner,requests))
