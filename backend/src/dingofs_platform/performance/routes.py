from .mdtest import OPTIONS, command_for
import mimetypes
import shlex
from datetime import timedelta
from fastapi import APIRouter,Depends,Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import defer
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.permissions import can_manage,require_manage
from dingofs_platform.inventory.service import audit
from dingofs_platform.resources.models import ManagedResource
from dingofs_platform.tool_packages.models import ToolJob
from .models import PerformanceRun,ACTIVE
from .schemas import RunInput,TestSpec
from .commands import argv_for
from .manager import now

router=APIRouter(prefix='/api/v1/performance',tags=['performance'])


def view(row,user,detail=False):
    data={k:getattr(row,k) for k in ('id','name','machine_id','creator_id','state','phase','progress','created_at','updated_at','finished_at','deadline','error','remote_root','cancel_requested')}
    data['can_manage']=can_manage(user,row)
    data['snapshot']=row.snapshot
    data['reports']={tool:{'state':value.get('state'),'error':value.get('error'),'tool':value.get('tool',tool),'parameters':value.get('parameters'),'summary':value.get('summary'),'remote_path':value.get('remote_path'),'command':value.get('command'),'files':list(value.get('artifacts',{}))} for tool,value in row.reports.items()} if detail else []
    if detail:data['log']=row.log
    return data


def accessible_machine(db,user,id):
    machine=db.get(Machine,id,with_for_update=True)
    if not machine:raise Problem(404,'not_found','机器不存在')
    require_manage(user,machine)
    if machine.archived or machine.maintenance:raise Problem(409,'unavailable','机器已归档或维护中')
    return machine


@router.get('/options')
def options(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        machines=[m for m in db.scalars(select(Machine).where(Machine.archived==False)) if can_manage(user,m)]
        mounts=[]
        for r in db.scalars(select(ManagedResource).where(ManagedResource.kind=='mount',ManagedResource.state=='mounted')):
            d=r.data
            if can_manage(user,r):mounts.append({'id':r.id,'name':r.name,'state':r.state,'machine_id':d.get('machine_id'),'path':d.get('mountpoint') or d.get('mount_point') or d.get('mount_path')})
        return {'machines':[{'id':m.id,'name':m.name,'address':m.address,'ssh_user':m.ssh_user,'maintenance':m.maintenance} for m in machines],
                'mdtest_options':OPTIONS,'mounts':mounts,'tools':['fio','elbencho','mdtest']}


@router.post('/preview')
def preview(payload:RunInput,request:Request,user=Depends(current_user)):
    with get_db(request) as db:accessible_machine(db,user,payload.machine_id)
    return {'tests':[{**scene,'mdtest_command':shlex.join(command_for(TestSpec(**scene['parameters']))) if scene['tool']=='mdtest' else None,'command':shlex.join(argv_for(TestSpec(**scene['parameters']),payload.target_path+'/platform-performance-<任务ID>/'+scene['id'],'<报告目录>/'+scene['id'],'dtt')).replace('__CUSTOM__','<本场景自定义脚本目录>')} for scene in payload.scenarios],
            'scene_count':len(payload.scenarios),
            'total_bytes':sum(int(scene['parameters']['total_size']) for scene in payload.scenarios)}


def enqueue(db,actor,payload,scenes,rerun_of=None):
    machine=accessible_machine(db,actor,payload.machine_id)
    if not machine.ssh_password_ciphertext:raise Problem(422,'ssh_password_missing','请先配置机器SSH密码')
    if db.scalar(select(PerformanceRun.id).where(PerformanceRun.machine_id==machine.id,PerformanceRun.state.in_(ACTIVE))):
        raise Problem(409,'performance_busy','该机器已有运行中或结果未确认的性能任务')
    if db.scalar(select(ToolJob.id).where(ToolJob.machine_id==machine.id,ToolJob.state=='running',ToolJob.deadline>now())):
        raise Problem(409,'tools_busy','该机器正在部署或检查工具，请等待完成')
    snapshot={**payload.model_dump(),'tests':[scene['parameters'] for scene in scenes],'scenarios':scenes,
              'machine_name':machine.name,'connection':[machine.address,machine.ssh_port,machine.ssh_user]}
    if rerun_of:snapshot['rerun_of']=rerun_of
    row=PerformanceRun(creator_id=actor.id,machine_id=machine.id,name=payload.name,snapshot=snapshot,
                       deadline=now()+timedelta(minutes=payload.timeout_minutes))
    db.add(row);db.flush()
    audit(db,actor,'performance.rerun' if rerun_of else 'performance.create','performance/'+row.id,[])
    return view(row,actor,True)


@router.post('/runs',status_code=202)
def create(payload:RunInput,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        return enqueue(db,actor_in_transaction(db,request),payload,payload.scenarios)


@router.post('/runs/{id}/rerun',status_code=202)
def rerun(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        original=db.get(PerformanceRun,id)
        if not original:raise Problem(404,'not_found','原测试任务不存在')
        require_manage(actor,original)
        if original.state in ACTIVE:raise Problem(409,'performance_busy','原任务尚未结束，不能重跑')
        old=original.snapshot
        specs=[TestSpec(**t) for t in old['tests']]
        # Already-expanded scenarios must never be multiplied into a new matrix.
        payload=RunInput(name=(original.name[:115]+' · 重跑'),machine_id=original.machine_id,
                         target_kind=old['target_kind'],target_path=old['target_path'],
                         cleanup_data=old.get('cleanup_data',False),timeout_minutes=old.get('timeout_minutes',120),tests=[specs[0].model_dump()])
        scenes=[{'id':f'scene-{index:03d}-{spec.tool}','tool':spec.tool,'parameters':spec.model_dump()} for index,spec in enumerate(specs,1)]
        return enqueue(db,actor,payload,scenes,rerun_of=id)


@router.get('/runs')
def listing(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        return [view(r,user) for r in db.scalars(select(PerformanceRun).options(defer(PerformanceRun.log),defer(PerformanceRun.reports)).order_by(PerformanceRun.created_at.desc()).limit(200))]


@router.get('/runs/{id}')
def detail(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=db.get(PerformanceRun,id)
        if not row:raise Problem(404,'not_found','测试任务不存在')
        return view(row,user,True)


@router.post('/runs/{id}/cancel')
def cancel(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        row=db.get(PerformanceRun,id,with_for_update=True)
        if not row:raise Problem(404,'not_found','测试任务不存在')
        require_manage(actor,row)
        if row.state not in ACTIVE:raise Problem(409,'finished','任务已经结束')
        row.cancel_requested=True
        if row.state!='queued':row.state='cancelling'
        audit(db,actor,'performance.cancel','performance/'+id,[])
        return view(row,actor,True)


@router.get('/runs/{id}/reports/{tool}/{filename}')
def artifact(id:str,tool:str,filename:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=db.get(PerformanceRun,id)
        content=row.reports.get(tool,{}).get('artifacts',{}).get(filename) if row else None
        if content is None:raise Problem(404,'not_found','报告附件不存在或超出平台收集大小限制，请查看远端报告目录')
        media='text/html' if filename=='index.html' else 'application/json' if filename.endswith('.json') else 'text/plain'
        headers={'Content-Security-Policy':"sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'",'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'}
        return Response(content,media_type=media,headers=headers)
