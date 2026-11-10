"""Functional runs bound to a registered cluster and exact case paths."""
import base64
from datetime import timedelta
from uuid import uuid4
import mimetypes
import re
from pathlib import PurePosixPath
import time
from fastapi import APIRouter,Depends,Request
from fastapi.responses import Response,JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import object_session
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster,Machine
from dingofs_platform.inventory.permissions import can_manage,require_manage
from dingofs_platform.inventory.service import audit
from dingofs_platform.tool_packages.models import ToolJob
from dingofs_platform.storage.models import StorageProfile
from dingofs_platform.storage.service import resolve as resolve_storage
from dingofs_platform.performance.models import PerformanceRun,ACTIVE as PERF_ACTIVE
from dingofs_platform.tool_packages.ssh_session import Remote
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from .catalog import catalogue,validate_selection
from .manager import now
from .models import FunctionalRun,FunctionalModuleRun,FunctionalEvent,FunctionalPreflight,ACTIVE
from .schemas import RunInput, RunInputV2, RunSpec
from . import submission  # noqa: F401 register guided persistence metadata
from .report_redaction import redact_report
from .reruns import RerunRequest, rerun_parent
from .environments.models import FunctionalEnvironmentProfile
from .environments.validation import validate_target
from .environments.service import member_machine_ids, validate_settings
from .drafts import Draft

router=APIRouter(prefix='/api/v1/functional',tags=['functional'])


@router.post('/preflight')
def guided_preflight(payload: RunSpec, request: Request, user=Depends(current_user)):
    if not request.app.state.settings.functional_guided_enabled:
        raise Problem(503, 'guided_runs_disabled', '引导功能测试尚未启用')
    from .preflight import resolve_submission, preflight
    with get_db(request) as db, db.begin():
        db.info['functional_settings'] = request.app.state.settings
        db.info['functional_preflight_transport'] = getattr(request.app.state, 'functional_preflight_transport', None)
        actor = actor_in_transaction(db, request)
        return preflight(db, actor, resolve_submission(db, actor, payload))

def catalog_path(request):
    return request.app.state.settings.functional_source_root

def view(row,detail=False,actor=None):
    value={key:getattr(row,key) for key in ('id','name','cluster_id','machine_id','creator_id','state','phase','progress','created_at','finished_at','error','cancel_requested')}
    value['snapshot']=row.snapshot
    if detail:value.update(log=row.log,result=row.result)
    if row.version==2:
        value['version']=2
        value['can_manage']=bool(actor and can_manage(actor,row))
        db=object_session(row)
        routes=row.snapshot.get('runtime_binding',{}).get('resolved_targets',[])
        value['children']=[]
        for child in db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id==row.id)
                               .order_by(FunctionalModuleRun.position)):
            target_ids={(target['host'],target['user']) for target in child.environment_snapshot['targets']}
            targets=[route for route in routes if (route['source_host'],route['user']) in target_ids]
            item={key:getattr(child,key) for key in ('id','module','position','state','cases','started_at',
                'deadline','finished_at','cancel_requested','error','result','environment_snapshot')}
            item.update(env_name=child.environment_snapshot['env_name'],stage=child.result.get('stage','waiting'),
                execution_targets=[{'machine_id':route['machine_id'],'name':route['machine_name'],
                                    'ip':route['address'],'user':route['user']} for route in targets],
                events=list(db.scalars(select(FunctionalEvent.record).where(FunctionalEvent.child_id==child.id)
                                       .order_by(FunctionalEvent.seq))))
            value['children'].append(item)
    return value

def cluster_and_machine(db,actor,id,machine_id=None):
    cluster=db.get(Cluster,id)
    if not cluster or cluster.archived:raise Problem(404,'not_found','集群不存在或已归档')
    require_manage(actor,cluster)
    machine=db.get(Machine,machine_id or cluster.management_machine_id)
    if not machine or machine.archived or machine.maintenance:raise Problem(409,'machine_unavailable','集群管理机器不可用')
    require_manage(actor,machine)
    return cluster,machine

def enqueue(db,actor,payload,cases,digest,hashes,rerun_of=None,fs_mode_override=None):
    cluster,machine=cluster_and_machine(db,actor,payload.cluster_id,payload.wizard.machine_id if payload.wizard else None)
    from dingofs_platform.operations.leases import require_available, legacy_functional_requests
    # Reserve the complete sorted lock set before taking the optional draft row
    # lock below. The account lock serializes profile/inventory changes.
    early_profile = db.get(FunctionalEnvironmentProfile,payload.environment_profile_id) if payload.environment_profile_id else None
    early_snapshot = {'env_name':payload.env_name,'selected':cases}
    if payload.wizard:
        early_snapshot['environment_profile_snapshot'] = {'kind':'custom',
            'machine_id':payload.wizard.machine_id,'settings':payload.wizard.settings}
    elif early_profile and early_profile.source_kind=='custom':
        early_snapshot['environment_profile_snapshot'] = {'kind':'custom',
            'machine_id':early_profile.machine_id,'settings':early_profile.settings}
    elif early_profile:
        early_snapshot['env_name'] = early_profile.source_key
        early_snapshot['environment_profile_snapshot'] = {'kind':'predefined',
            'source_file':early_profile.source_file,
            'source_file_sha':early_profile.display.get('source_file_sha'),
            'storage_file_sha':early_profile.display.get('storage_file_sha')}
    requests = legacy_functional_requests(db,cluster.id,machine.id,early_snapshot,
        db.info.get('functional_source_root'),actor=actor,strict=True)
    require_available(db,requests)
    if not machine.ssh_password_ciphertext:raise Problem(422,'ssh_password_missing','请配置管理机器 SSH 密码')
    if db.scalar(select(FunctionalRun.id).where(FunctionalRun.cluster_id==cluster.id,FunctionalRun.state.in_(ACTIVE))):
        raise Problem(409,'functional_busy','集群有进行中的功能测试')
    if db.scalar(select(PerformanceRun.id).where(PerformanceRun.machine_id==machine.id,PerformanceRun.state.in_(PERF_ACTIVE))):
        raise Problem(409,'performance_busy','管理机器有进行中的性能测试')
    if db.scalar(select(ToolJob.id).where(ToolJob.machine_id==machine.id,ToolJob.action!='check',ToolJob.state=='running',ToolJob.deadline>now())):
        raise Problem(409,'tools_busy','机器正在部署工具')
    addresses=(cluster.status_snapshot or {}).get('mds_addresses') or []
    if not addresses:raise Problem(422,'cluster_status_required','请先刷新集群状态以获取 MDS 地址')
    environment=payload.model_dump(exclude={'wizard','draft_id','draft_revision'})
    profile=None
    if payload.draft_id:
        draft=db.get(Draft,payload.draft_id,with_for_update=True)
        if not draft or draft.creator_id!=actor.id:raise Problem(404,'not_found','草稿不存在')
        if draft.state!='draft' or draft.revision!=payload.draft_revision:
            raise Problem(409,'revision_conflict','草稿已提交或版本发生变化')
    if payload.wizard:
        wizard=payload.wizard
        validate_settings(wizard.settings)
        if wizard.machine_id!=machine.id:raise Problem(422,'target_mismatch','执行机器不一致')
        storage=db.get(StorageProfile,wizard.storage_profile_id)
        if not storage or storage.deleted or not storage.enabled:
            raise Problem(422,'storage_unavailable','存储配置不可用')
        require_manage(actor,storage)
        settings=dict(wizard.settings)
        if wizard.fs_mode=='existing':
            settings['fs_prefix']=wizard.existing_fs_name
            settings['clients']=[{**client,'fs_name':wizard.existing_fs_name} for client in settings.get('clients',[])]
        else:
            settings['fs_prefix']=str(settings.get('fs_prefix') or 'functional')[:40]+'-'+uuid4().hex[:12]
        profile=FunctionalEnvironmentProfile(creator_id=actor.id,name=('向导-'+uuid4().hex[:12]),
            source_kind='custom',cluster_id=cluster.id,machine_id=machine.id,
            storage_profile_id=storage.id,storage_profile_revision=storage.revision,
            settings=settings,display={'wizard':not wizard.save_as_environment},enabled=True,
            validation='needs_validation')
        db.add(profile);db.flush()
        environment['environment_profile_id']=profile.id
        environment['environment_profile_revision']=profile.revision
        environment['fs_mode']=wizard.fs_mode
    if fs_mode_override:
        environment['fs_mode']=fs_mode_override
    if environment.get('environment_profile_id'):
        profile=profile or db.get(FunctionalEnvironmentProfile,environment['environment_profile_id'])
        if not profile or profile.deleted:raise Problem(404,'not_found','测试环境不存在')
        if profile.revision!=environment['environment_profile_revision']:
            raise Problem(409,'environment_changed','测试环境已修改，请刷新后重试')
        client_machine=db.get(Machine,profile.machine_id) if profile.source_kind=='custom' else machine
        if profile.source_kind=='custom':
            if not client_machine or client_machine.archived or client_machine.maintenance:
                raise Problem(422,'machine_unavailable','测试机不可用')
            require_manage(actor,client_machine)
            members={}
            for member_id in member_machine_ids(profile.settings,profile.machine_id):
                member=db.get(Machine,member_id)
                if not member or member.archived or member.maintenance:raise Problem(422,'machine_unavailable','客户端或缓存成员机器不可用')
                require_manage(actor,member)
                members[member_id]=[member.address,member.ssh_port,member.ssh_user]
            if len({entry[2] for entry in members.values()})>1:
                raise Problem(422,'ssh_identity_mismatch','当前测试工具只支持所有客户端和缓存机器使用同一 SSH 用户')
            if not profile.storage_profile_id:raise Problem(422,'storage_unavailable','自建环境需要已启用的存储配置')
            storage=db.get(StorageProfile,profile.storage_profile_id)
            if not storage or storage.deleted or not storage.enabled or storage.revision!=profile.storage_profile_revision:
                raise Problem(422,'storage_unavailable','存储配置已改变或不可用，请编辑并重新验证环境')
            require_manage(actor,storage)
        known=set()
        for host in db.scalars(select(Machine).where(Machine.archived==False,Machine.maintenance==False)):
            if can_manage(actor,host):known.update({host.address,host.name,*host.aliases})
        validate_target(profile,cluster,client_machine,db.info.get('functional_source_root'),cases,known)
        environment['env_name']=profile.source_key if profile.source_kind=='predefined' else 'env_platform_'+profile.id.replace('-','')
        if profile.source_kind=='custom':
            environment['binaries']={**profile.settings.get('binaries',{}),**payload.binaries}
        environment['environment_profile_snapshot']={
            'id':profile.id,'revision':profile.revision,'kind':profile.source_kind,
            'digest':profile.source_digest,'source_file':profile.source_file,
            'source_file_sha':profile.display.get('source_file_sha'),
            'storage_file_sha':profile.display.get('storage_file_sha'),
            'cluster_id':profile.cluster_id,'machine_id':profile.machine_id,
            'storage_profile_id':profile.storage_profile_id,'storage_profile_revision':profile.storage_profile_revision,
            'settings':profile.settings,'dingo_tool_path':cluster.resolved_dingo_path or cluster.dingo_path,
            'client_connection':[client_machine.address,client_machine.ssh_port,client_machine.ssh_user],
            'member_connections':members if profile.source_kind=='custom' else {}}
    snapshot={**environment,'selected':cases,'mds_addr':','.join(addresses),
              'cluster_name':cluster.name,'external_name':cluster.external_name,'machine_name':machine.name,
              'connection':[machine.address,machine.ssh_port,machine.ssh_user],'catalog_digest':digest,'hashes':hashes}
    if rerun_of:snapshot['rerun_of']=rerun_of
    row=FunctionalRun(creator_id=actor.id,cluster_id=cluster.id,machine_id=machine.id,name=payload.name,
                      snapshot=snapshot,deadline=now()+timedelta(minutes=payload.timeout_minutes))
    db.add(row);db.flush()
    if payload.draft_id:
        draft.state='submitted';draft.run_id=row.id;draft.revision+=1
    audit(db,actor,'functional.rerun' if rerun_of else 'functional.create','functional/'+row.id,[])
    return view(row,True)

@router.get('/guided/metadata')
def guided_metadata(request: Request, user=Depends(current_user)):
    from .guided_options import metadata
    with get_db(request) as db:
        return metadata(db, user, request.app.state.settings)


@router.post('/guided/compatibility')
def guided_compatibility(payload: RunSpec, request: Request, user=Depends(current_user)):
    from .guided_options import compatibility
    with get_db(request) as db:
        return compatibility(db, user, payload, request.app.state.settings)


@router.get('/options')
def options(request:Request,user=Depends(current_user)):
    data=catalogue(catalog_path(request))
    with get_db(request) as db:
        clusters=[]
        machines=[{'id':m.id,'name':m.name,'address':m.address,'ssh_user':m.ssh_user} for m in db.scalars(select(Machine).where(Machine.archived==False,Machine.maintenance==False)) if can_manage(user,m)]
        for cluster in db.scalars(select(Cluster).where(Cluster.archived==False)):
            if not can_manage(user,cluster):continue
            machine=db.get(Machine,cluster.management_machine_id)
            if machine and can_manage(user,machine):clusters.append({'id':cluster.id,'name':cluster.name,'machine':machine.name,'external_name':cluster.external_name,'mds_addresses':(cluster.status_snapshot or {}).get('mds_addresses') or []})
    data['clusters']=clusters
    data['machines']=machines
    env_dir=catalog_path(request).parent/'conf/env'
    names=set()
    if env_dir.is_dir():
        for path in env_dir.glob('env_*.yaml'):
            names.update(re.findall(r'^\s*(env_[A-Za-z0-9_-]+):\s*(?:#.*)?$',path.read_text(errors='replace'),re.M))
    data['environments']=sorted(names)
    return data

@router.post('/runs',status_code=202)
def create(payload:RunInput|RunInputV2,request:Request,user=Depends(current_user)):
    if isinstance(payload,RunInputV2):
        if not request.app.state.settings.functional_guided_enabled:
            raise Problem(503,'guided_runs_disabled','引导功能测试尚未启用')
        from .preflight import resolve_submission,validate_preflight
        with get_db(request) as db,db.begin():
            db.info['functional_settings']=request.app.state.settings
            db.info['functional_preflight_transport']=getattr(request.app.state,'functional_preflight_transport',None)
            actor=actor_in_transaction(db,request)
            existing=db.scalar(select(FunctionalRun).where(FunctionalRun.creator_id==actor.id,
                                FunctionalRun.idempotency_key==payload.idempotency_key))
            if existing:
                require_manage(actor,existing)
                if any(existing.snapshot.get(k)!=v for k,v in payload.model_dump(mode='json',include=set(RunSpec.model_fields)).items()):
                    raise Problem(409,'idempotency_conflict','幂等键已经用于不同的请求')
                return view(existing,True,actor)
            normalized=resolve_submission(db,actor,payload)
            trusted=validate_preflight(db,actor,normalized,payload.preflight_token,payload.confirmed_impacts)
            row=submission.create_run(db,actor,normalized,runtime_binding=trusted['runtime_binding'])
            db.get(FunctionalPreflight,trusted['preflight_id']).consumed_by=row.id
            return view(row,True,actor)
    data=catalogue(catalog_path(request))
    if data['digest']!=payload.catalog_digest:raise Problem(409,'catalog_changed','用例目录已更新，请刷新后重新选择')
    try:cases=validate_selection(data,payload.selected)
    except ValueError as exc:raise Problem(422,'invalid_cases',str(exc)) from exc
    hashes={module:{row['path']:row['sha256'] for row in data['modules'][module] if row['path'] in paths} for module,paths in cases.items()}
    with get_db(request) as db,db.begin():
        db.info['functional_source_root']=catalog_path(request)
        actor=actor_in_transaction(db,request)
        profile=db.get(FunctionalEnvironmentProfile,payload.environment_profile_id) if payload.environment_profile_id else None
        if request.app.state.settings.functional_guided_enabled and not payload.wizard and (not profile or profile.source_kind=='predefined'):
            from .preflight import resolve_submission,preflight
            from .schemas import ModuleSelection
            if payload.binaries:
                raise Problem(422,'guided_submission_required','现有环境必须通过引导预检；不支持二进制覆盖')
            if not profile:
                matches=list(db.scalars(select(FunctionalEnvironmentProfile).where(
                    FunctionalEnvironmentProfile.source_kind=='predefined',
                    FunctionalEnvironmentProfile.source_key==payload.env_name,
                    FunctionalEnvironmentProfile.deleted==False)))
                if len(matches)!=1:
                    raise Problem(422,'guided_submission_required','请先同步预置环境，然后通过引导预检提交')
                profile=matches[0]
            spec=RunSpec(name=payload.name,cluster_id=payload.cluster_id,catalog_digest=payload.catalog_digest,
                retries=payload.retries,timeout_minutes=payload.timeout_minutes,
                module_plans=[ModuleSelection(module=module,cases=paths,environment_profile_id=profile.id,
                    environment_profile_revision=payload.environment_profile_revision or profile.revision)
                    for module,paths in cases.items()])
            db.info['functional_settings']=request.app.state.settings
            db.info['functional_preflight_transport']=getattr(request.app.state,'functional_preflight_transport',None)
            checked=preflight(db,actor,resolve_submission(db,actor,spec))
            # Commit the real token, but never infer confirmation from an old
            # payload that cannot express confirmations or an idempotency key.
            return JSONResponse(status_code=409,content={'code':'guided_submission_required',
                'message':'请升级为 version=2 提交，提供幂等键并确认预检影响。',
                'details':{'submission':spec.model_dump(mode='json'),'preflight':checked.model_dump(mode='json')}})
        return enqueue(db,actor,payload,cases,data['digest'],hashes)

@router.get('/runs')
def listing(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        return [view(row,actor=user) for row in db.scalars(select(FunctionalRun).order_by(FunctionalRun.created_at.desc()).limit(200)) if can_manage(user,row)]

@router.get('/runs/{id}')
def detail(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=db.get(FunctionalRun,id)
        if not row:raise Problem(404,'not_found','任务不存在')
        require_manage(user,row)
        return view(row,True,user)

@router.post('/runs/{id}/stop')
def stop(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        row=db.get(FunctionalRun,id,with_for_update=True)
        if not row:raise Problem(404,'not_found','任务不存在')
        require_manage(actor,row)
        if row.state not in ACTIVE:raise Problem(409,'not_running','任务已经结束')
        row.cancel_requested=True;row.phase='正在停止：等待当前用例结束'
        return view(row,True,user)

@router.post('/runs/{id}/rerun',status_code=202)
def rerun(id:str,request:Request,failed_only:bool=False,payload:RerunRequest|None=None,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request);original=db.get(FunctionalRun,id)
        if not original:raise Problem(404,'not_found','原任务不存在')
        require_manage(actor,original)
        if original.version==2:
            if payload is None:
                raise Problem(409,'guided_rerun_required','请确认重跑模块与机器并提供幂等键')
            db.info['functional_settings']=request.app.state.settings
            db.info['functional_preflight_transport']=getattr(request.app.state,'functional_preflight_transport',None)
            return view(rerun_parent(db,actor,id,failed_only,payload.idempotency_key),True,actor)
        if original.state in ACTIVE:raise Problem(409,'busy','任务尚未结束')
        old=original.snapshot;cases=old['selected']
        if failed_only:
            failed={(r.get('module'),r.get('case')) for r in (original.result or {}).get('cases',[]) if r.get('status') in ('FAIL','ERROR')}
            cases={module:[name for name in names if (module,name) in failed] for module,names in cases.items()}
            cases={module:names for module,names in cases.items() if names}
            if not cases:raise Problem(422,'no_failed_cases','没有可重跑的失败用例')
        data=catalogue(catalog_path(request))
        if data['digest']!=old['catalog_digest']:raise Problem(409,'catalog_changed','用例版本已变化，不能直接重跑')
        payload=RunInput(**{key:old[key] for key in ('cluster_id','retries','timeout_minutes','binaries')},
                         **({'environment_profile_id':old['environment_profile_id'],'environment_profile_revision':old['environment_profile_revision']} if old.get('environment_profile_id') else {'env_name':old['env_name']}),
                         name=(original.name[:105]+' · '+('失败重跑' if failed_only else '重跑')),
                         selected=cases,catalog_digest=data['digest'])
        db.info['functional_source_root']=catalog_path(request)
        return enqueue(db,actor,payload,cases,data['digest'],{module:{path:old['hashes'][module][path] for path in paths} for module,paths in cases.items()},rerun_of=id,fs_mode_override=old.get('fs_mode'))

@router.get('/runs/{id}/modules/{child_id}/report/{path:path}')
def module_report(id:str,child_id:str,path:str,request:Request,user=Depends(current_user)):
    from .reports import download_report
    with get_db(request) as db:
        db.info['functional_settings']=request.app.state.settings
        db.info['functional_report_transport']=getattr(request.app.state,'functional_report_transport',None)
        data,media=download_report(db,user,id,child_id,path)
    return Response(data,media_type=media,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.post('/runs/{id}/resources/verify')
def verify_resources(id:str,request:Request,user=Depends(current_user)):
    from dataclasses import asdict
    from .retention import verify_retained_resources
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        db.info['functional_settings']=request.app.state.settings
        db.info['functional_retention_transport']=getattr(request.app.state,'functional_retention_transport',None)
        return asdict(verify_retained_resources(db,actor,id))


@router.get('/runs/{id}/report/{path:path}')
def report(id:str,path:str,request:Request,user=Depends(current_user)):
    rel=PurePosixPath(path)
    if not path or rel.is_absolute() or '..' in rel.parts:raise Problem(404,'not_found','报告文件不存在')
    with get_db(request) as db:
        row=db.get(FunctionalRun,id)
        if not row:raise Problem(404,'not_found','任务不存在')
        if row.version==2:
            require_manage(user,row)
            raise Problem(409,'child_report_required','请使用对应模块的已验证报告入口')
        require_manage(user,row)
        machine=db.get(Machine,row.machine_id)
        password=decrypt_password(machine.ssh_password_ciphertext,request.app.state.settings.credential_encryption_key)
        config=SSHConfig(machine.address,machine.ssh_port,machine.ssh_user,password)
        secrets=[]
        environment=(row.snapshot or {}).get('environment_profile_snapshot') or {}
        if environment.get('kind')=='custom':
            storage,_=resolve_storage(db,environment['storage_profile_id'],environment['storage_profile_revision'],request.app.state.settings.credential_encryption_key)
            client=db.get(Machine,environment['machine_id'])
            if not client or not client.ssh_password_ciphertext:
                raise Problem(503,'report_redaction_unavailable','无法安全读取旧报告的脱敏凭据')
            client_password=decrypt_password(client.ssh_password_ciphertext,request.app.state.settings.credential_encryption_key)
            secrets=[client_password,*[value for key,value in storage.items() if key in ('s3_ak','s3_sk','rados_key')]]
    root=".local/share/dingofs-platform/functional/"+id+"/output/int_allure_report/allure-report-latest"
    code='ROOT='+repr(root)+'\nREL='+repr(path)+'''\nimport base64,json
from pathlib import Path
output=(Path.home()/ROOT).parent.parent.resolve()
root=(Path.home()/ROOT).resolve()
if not root.is_dir():
    # Older failed runs generated the module report before the dtt summary step.
    candidates=sorted(output.glob('integration_*/*/allure-report-latest'))
    if candidates:root=candidates[-1].resolve()
file=(root/REL).resolve()
if not root.is_relative_to(output) or not file.is_relative_to(root) or not file.is_file() or file.stat().st_size>8*1024*1024:
    print(json.dumps({'missing':True}))
else:print(json.dumps({'data':base64.b64encode(file.read_bytes()).decode()}))
'''
    remote=Remote(config,time.monotonic()+60,lambda **kw:None,'功能报告')
    try:raw=remote.python(code,'读取报告',max_bytes=12*1024*1024)
    finally:remote.close()
    if raw.get('missing'):raise Problem(404,'report_unavailable','报告尚未生成或文件不存在，请先查看执行日志')
    media=mimetypes.guess_type(path)[0] or 'application/octet-stream'
    data=base64.b64decode(raw['data'])
    if secrets and (media.startswith('text/') or media in ('application/json','application/javascript','application/xml')):
        data=redact_report(data,secrets)
    return Response(data,media_type=media)
