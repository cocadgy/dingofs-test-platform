from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster,Machine
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.permissions import can_manage,require_manage
from dingofs_platform.inventory.service import audit
from dingofs_platform.storage.models import StorageProfile
from .models import FunctionalEnvironmentProfile as Profile
from .schemas import ProfileInput,ProfileUpdate
from .service import view,validate_settings,sync_predefined,member_machine_ids
from .validation import validate_target
from .preflight import probe,PROBE_CODE,CLIENT_PROBE_CODE,CACHE_PROBE_CODE

router=APIRouter(prefix='/api/v1/functional/environments',tags=['functional-environments'])

def target(db,actor,payload):
    for model,id in ((Cluster,payload.cluster_id),(Machine,payload.machine_id)):
        row=db.get(model,id)
        if not row or row.archived:raise Problem(404,'not_found','目标集群或机器不存在')
        require_manage(actor,row)
    for machine_id in member_machine_ids(payload.settings,payload.machine_id):
        member=db.get(Machine,machine_id)
        if not member or member.archived or member.maintenance:raise Problem(422,'machine_unavailable','客户端或缓存成员机器不可用')
        require_manage(actor,member)
    if payload.storage_profile_id:
        storage=db.get(StorageProfile,payload.storage_profile_id)
        if not storage or storage.deleted or not storage.enabled:raise Problem(422,'storage_unavailable','存储配置不存在或未启用')
        require_manage(actor,storage)
        return storage.revision
    return None

def getrow(db,id):
    row=db.get(Profile,id)
    if not row or row.deleted:raise Problem(404,'not_found','测试环境不存在')
    return row

@router.get('')
def listing(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        return [view(row,user,db) for row in db.scalars(select(Profile).where(Profile.deleted==False).order_by(Profile.source_kind,Profile.name)) if not (row.display or {}).get('wizard')]

@router.post('/sync-predefined')
def sync(request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        if actor.role!='admin':raise Problem(403,'forbidden','仅管理员可同步预置环境')
        result=sync_predefined(db,request.app.state.settings.functional_source_root.parent/'conf/env')
        audit(db,actor,'functional_environment.sync','functional/environments',[])
        return result

@router.post('',status_code=201)
def create(payload:ProfileInput,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        validate_settings(payload.settings)
        storage_revision=target(db,actor,payload)
        row=Profile(creator_id=actor.id,name=payload.name,source_kind='custom',
                    cluster_id=payload.cluster_id,machine_id=payload.machine_id,
                    storage_profile_id=payload.storage_profile_id,storage_profile_revision=storage_revision,
                    settings=payload.settings,display={},enabled=payload.enabled,
                    validation='needs_validation')
        db.add(row);db.flush()
        audit(db,actor,'functional_environment.create','functional/environments/'+row.id,[])
        return view(row,actor,db)

@router.get('/{id}')
def detail(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:return view(getrow(db,id),user,db)

@router.put('/{id}')
def update(id:str,payload:ProfileUpdate,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request);row=getrow(db,id)
        if row.source_kind!='custom':raise Problem(409,'read_only','预置环境不可编辑，请先复制')
        require_manage(actor,row)
        if row.revision!=payload.revision:raise Problem(409,'revision_conflict','测试环境已更新，请刷新')
        validate_settings(payload.settings);storage_revision=target(db,actor,payload)
        for key in ('name','cluster_id','machine_id','storage_profile_id','settings','enabled'):
            setattr(row,key,getattr(payload,key))
        row.storage_profile_revision=storage_revision;row.validation='needs_validation';row.display={};row.revision+=1
        db.flush();audit(db,actor,'functional_environment.update','functional/environments/'+id,[])
        return view(row,actor,db)

@router.get('/{id}/copy-settings')
def copy_settings(id:str,request:Request,user=Depends(current_user)):
    from .copy_settings import preview
    with get_db(request) as db:
        row=getrow(db,id)
        return preview(row,request.app.state.settings.functional_source_root.parent/'conf/env')

@router.post('/{id}/copy',status_code=201)
def copy(id:str,payload:ProfileInput,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request);source=getrow(db,id)
        validate_settings(payload.settings);storage_revision=target(db,actor,payload)
        row=Profile(creator_id=actor.id,name=payload.name,source_kind='custom',cluster_id=payload.cluster_id,
                    machine_id=payload.machine_id,storage_profile_id=payload.storage_profile_id,
                    storage_profile_revision=storage_revision,settings=payload.settings,display={},
                    enabled=payload.enabled,validation='needs_validation')
        db.add(row);db.flush();audit(db,actor,'functional_environment.copy','functional/environments/'+row.id,[])
        return view(row,actor,db)

@router.delete('/{id}',status_code=204)
def delete(id:str,request:Request,user=Depends(current_user),revision:int=0):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request);row=getrow(db,id)
        if row.source_kind!='custom':raise Problem(409,'read_only','预置环境不可删除')
        require_manage(actor,row)
        if row.revision!=revision:raise Problem(409,'revision_conflict','测试环境已更新，请刷新')
        row.deleted=True;row.enabled=False;row.revision+=1
        audit(db,actor,'functional_environment.delete','functional/environments/'+id,[])

@router.get('/{id}/validate')
def validate(id:str,cluster_id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=getrow(db,id);cluster=db.get(Cluster,cluster_id)
        if not cluster or cluster.archived:raise Problem(404,'not_found','集群不存在')
        require_manage(user,cluster)
        machine=db.get(Machine,row.machine_id if row.source_kind=='custom' else cluster.management_machine_id)
        if not machine or machine.archived or machine.maintenance:raise Problem(422,'machine_unavailable','测试机不可用')
        require_manage(user,machine)
        known=set()
        for host in db.scalars(select(Machine).where(Machine.archived==False,Machine.maintenance==False)):
            if can_manage(user,host):known.update({host.address,host.name,*host.aliases})
        validate_target(row,cluster,machine,request.app.state.settings.functional_source_root,{},known)
        if row.source_kind=='custom':
            for machine_id in member_machine_ids(row.settings,row.machine_id):
                member=db.get(Machine,machine_id)
                if not member or member.archived or member.maintenance:raise Problem(422,'machine_unavailable','客户端或缓存成员机器不可用')
                require_manage(user,member)
        if row.source_kind=='custom':
            storage=db.get(StorageProfile,row.storage_profile_id) if row.storage_profile_id else None
            if not storage or storage.deleted or not storage.enabled or storage.revision!=row.storage_profile_revision:
                raise Problem(422,'storage_unavailable','存储配置已修改或不可用')
            require_manage(user,storage)
        return {'valid':True,'environment_id':row.id,'revision':row.revision}

@router.post('/{id}/preflight')
def preflight(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=getrow(db,id)
        if row.source_kind!='custom':raise Problem(422,'predefined_environment','预置环境无需自建预检')
        require_manage(user,row)
        cluster=db.get(Cluster,row.cluster_id);client=db.get(Machine,row.machine_id)
        if not cluster or cluster.archived or not client or client.archived or client.maintenance:
            raise Problem(422,'target_unavailable','目标集群或机器不可用')
        require_manage(user,cluster);require_manage(user,client)
        management=db.get(Machine,cluster.management_machine_id)
        if not management or management.archived or management.maintenance:
            raise Problem(422,'target_unavailable','集群管理机器不可用')
        require_manage(user,management)
        validate_target(row,cluster,client,request.app.state.settings.functional_source_root,{})
        members=[]
        for machine_id in member_machine_ids(row.settings,row.machine_id):
            member=db.get(Machine,machine_id)
            if not member or member.archived or member.maintenance:raise Problem(422,'machine_unavailable','客户端或缓存成员机器不可用')
            require_manage(user,member);members.append(member)
        storage=db.get(StorageProfile,row.storage_profile_id) if row.storage_profile_id else None
        if not storage or storage.deleted or not storage.enabled or storage.revision!=row.storage_profile_revision:
            raise Problem(422,'storage_unavailable','存储配置已变化或不可用')
        require_manage(user,storage)
        key=request.app.state.settings.credential_encryption_key
        try:
            identities={(member.ssh_user,decrypt_password(member.ssh_password_ciphertext,key)) for member in [client,*members]}
            if len(identities)>1:raise ValueError('所有客户端和缓存机器需要相同的 SSH 用户及密码')
            management_checks=probe(management,key,'DINGO_PATH='+repr(cluster.resolved_dingo_path or cluster.dingo_path or '')+'\n'+PROBE_CODE)
            items=[{'name':name,'success':bool(value)} for name,value in management_checks.items()]
            client_ids={item['machine_id'] for item in row.settings.get('clients',[])} if 'clients' in row.settings else {row.machine_id}
            cache_ids={item['machine_id'] for item in row.settings.get('remote_caches',[])}
            for member in members:
                if member.id in client_ids:
                    client_checks=probe(member,key,'CLIENT_PATH='+repr(row.settings.get('binaries',{}).get('dingo-client',''))+'\nMOUNT_ROOT='+repr(row.settings.get('mount_root',''))+'\n'+CLIENT_PROBE_CODE)
                    items.extend({'name':member.name+' · '+name,'success':bool(value)} for name,value in client_checks.items())
                if member.id in cache_ids:
                    cache_checks=probe(member,key,'CACHE_PATH='+repr(row.settings.get('binaries',{}).get('dingo-cache',''))+'\n'+CACHE_PROBE_CODE)
                    items.extend({'name':member.name+' · '+name,'success':bool(value)} for name,value in cache_checks.items())
        except Exception as exc:
            items=[{'name':'ssh','success':False,'message':type(exc).__name__}]
        success=bool(items) and all(item['success'] for item in items)
    with get_db(request) as db,db.begin():
        current=db.get(Profile,id,with_for_update=True)
        if current and current.revision==row.revision:
            current.validation='ready' if success else 'failed'
            current.display={**(current.display or {}),'validated_at':datetime.now(timezone.utc).isoformat(),'checks':items}
            audit(db,user,'functional_environment.preflight','functional/environments/'+id,[])
    return {'success':success,'items':items}
