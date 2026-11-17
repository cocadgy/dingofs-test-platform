"""User-owned, versioned drafts for the functional test wizard."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, ForeignKey, String, select
from sqlalchemy.orm import Mapped, mapped_column
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import Base, Record, get_db
from dingofs_platform.errors import Problem

router = APIRouter(prefix='/api/v1/functional/drafts', tags=['functional-drafts'])

class Draft(Record, Base):
    __tablename__ = 'functional_drafts'
    creator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(120))
    step: Mapped[int] = mapped_column(default=1)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default='draft')
    run_id: Mapped[str | None] = mapped_column(ForeignKey('functional_runs.id'), nullable=True)

class CreateDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1,max_length=120)
    step: int = Field(ge=1,le=6)
    configuration: dict = Field(default_factory=dict)

class UpdateDraft(CreateDraft):
    revision: int = Field(ge=1)

def safe(value, depth=0):
    if depth>8: raise Problem(422,'invalid_draft','草稿嵌套过深')
    if isinstance(value,dict):
        for key,item in value.items():
            if not isinstance(key,str) or any(secret in key.lower() for secret in ('password','secret','token','credential','s3_ak','s3_sk','rados_key')):
                raise Problem(422,'draft_secret','草稿不能保存密码或密钥')
            safe(item,depth+1)
    elif isinstance(value,list):
        if len(value)>2000:raise Problem(422,'invalid_draft','草稿条目过多')
        for item in value:safe(item,depth+1)
    elif not (value is None or isinstance(value,(str,int,float,bool))):
        raise Problem(422,'invalid_draft','草稿字段格式错误')
    elif isinstance(value,str) and len(value)>4096:
        raise Problem(422,'invalid_draft','草稿字段过长')

def view(row):
    return {key:getattr(row,key) for key in ('id','name','step','configuration','state','run_id','revision','created_at','updated_at')}

def owned(db,id,user):
    row=db.get(Draft,id)
    if not row or row.creator_id!=user.id:raise Problem(404,'not_found','草稿不存在')
    return row

@router.get('')
def listing(request:Request,user=Depends(current_user)):
    with get_db(request) as db:
        return [view(row) for row in db.scalars(select(Draft).where(Draft.creator_id==user.id,Draft.state=='draft').order_by(Draft.updated_at.desc()))]

@router.post('',status_code=201)
def create(payload:CreateDraft,request:Request,user=Depends(current_user)):
    safe(payload.configuration)
    with get_db(request) as db,db.begin():
        actor=actor_in_transaction(db,request)
        row=Draft(creator_id=actor.id,**payload.model_dump())
        db.add(row);db.flush();return view(row)

@router.get('/{id}')
def detail(id:str,request:Request,user=Depends(current_user)):
    with get_db(request) as db:return view(owned(db,id,user))

@router.put('/{id}')
def update(id:str,payload:UpdateDraft,request:Request,user=Depends(current_user)):
    safe(payload.configuration)
    with get_db(request) as db,db.begin():
        row=owned(db,id,actor_in_transaction(db,request))
        if row.state!='draft':raise Problem(409,'draft_submitted','草稿已经提交')
        if row.revision!=payload.revision:raise Problem(409,'revision_conflict','草稿已在其他页面修改，请重新载入')
        row.name=payload.name;row.step=payload.step;row.configuration=payload.configuration;row.revision+=1
        db.flush();return view(row)

@router.delete('/{id}',status_code=204)
def delete(id:str,revision:int,request:Request,user=Depends(current_user)):
    with get_db(request) as db,db.begin():
        row=owned(db,id,actor_in_transaction(db,request))
        if row.revision!=revision:raise Problem(409,'revision_conflict','草稿已在其他页面修改，请重新载入')
        db.delete(row)
