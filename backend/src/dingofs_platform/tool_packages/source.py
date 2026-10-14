from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from dingofs_platform.auth.dependencies import current_user, require_admin
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.service import audit
from .models import ToolSource
from .automatic import DTT_IMAGE

router=APIRouter(prefix='/api/v1',tags=['tool-packages'])
DEFAULT_DIRECTORY='/mnt/disk5/daigy/dingofs-testsuite-tool'


class SourceInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    machine_id:str
    directory:str=Field(default=DEFAULT_DIRECTORY,max_length=512)
    image:str=Field(default=DTT_IMAGE,max_length=512,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$')
    allow_cached:bool=False
    revision:int=0

    @field_validator('directory')
    @classmethod
    def absolute(cls,value):
        if not value.startswith('/') or any(ord(c)<32 for c in value):raise ValueError('需要绝对目录路径')
        return value


def get_source(db):
    row=db.get(ToolSource,'default')
    if not row:raise Problem(422,'tool_source_missing','请管理员先在配置管理 → 工具包管理中保存平台工具来源')
    return row


@router.get('/tool-source')
def source(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        row=db.get(ToolSource,'default')
        machines=list(db.scalars(select(Machine).where(Machine.archived==False).order_by(Machine.name)))
        suggested=next((m.id for m in machines if m.address=='172.30.14.126'), '')
        data={key:getattr(row,key) for key in ('machine_id','directory','image','allow_cached','revision')} if row else {'machine_id':suggested,'directory':DEFAULT_DIRECTORY,'image':DTT_IMAGE,'allow_cached':False,'revision':0}
        return {'source':data,'configured':bool(row),'can_manage':user.role=='admin','user_id':user.id,
                'machines':[{'id':m.id,'name':m.name,'address':m.address,'ssh_user':m.ssh_user,'can_manage':user.role=='admin' or m.creator_id==user.id} for m in machines]}


@router.put('/tool-source')
def save(payload:SourceInput,request:Request,user=Depends(require_admin)):
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request,admin=True)
        machine=db.get(Machine,payload.machine_id)
        if not machine or machine.archived or not machine.ssh_password_ciphertext:
            raise Problem(422,'source_unavailable','请选择已配置 SSH 密码的有效平台机器')
        row=db.get(ToolSource,'default',with_for_update=True)
        if (row.revision if row else 0)!=payload.revision:raise Problem(409,'revision_conflict','工具来源已修改，请刷新后重试')
        values=payload.model_dump(exclude={'revision'})
        if row:
            for key,value in values.items():setattr(row,key,value)
            row.revision+=1
        else:
            row=ToolSource(id='default',**values);db.add(row)
        db.flush()
        audit(db,actor,'tool_source.save','tool-source',values.keys())
        return {**values,'revision':row.revision}
