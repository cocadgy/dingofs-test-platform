from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from dingofs_platform.auth.dependencies import current_user, require_admin
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.permissions import require_manage
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from dingofs_platform.inventory.service import audit
from .models import ToolPackage, ToolJob
from .bundle import inspect_bundle
from .service import view, expire, run_job
from .source import get_source

router = APIRouter(prefix='/api/v1', tags=['tool-packages'])


class ImportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    directory: str = Field(min_length=1, max_length=512)


class JobInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['check', 'install', 'auto_install']
    package_id: str | None = None
    tool: Literal['dtt','dingo','dingo-client','dingo-cache'] | None = None


@router.get('/tool-packages')
def packages(request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        return {'can_manage': user.role == 'admin', 'items': [view(row) for row in db.scalars(select(ToolPackage).order_by(ToolPackage.created_at.desc()))]}


@router.post('/tool-packages', status_code=201)
def publish(payload: ImportInput, request: Request, user=Depends(require_admin)):
    try:
        data = inspect_bundle(request.app.state.settings.tool_bundle_root, payload.directory)
    except (ValueError, OSError, TypeError) as exc:
        raise Problem(422, 'invalid_bundle', str(exc)) from None
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request, admin=True)
        row = db.scalar(select(ToolPackage).where(ToolPackage.digest == data['digest']))
        if row:
            return view(row)
        row = ToolPackage(creator_id=actor.id, manifest=data, **{k:data[k] for k in ('tool','version','architecture','directory','digest','size_bytes')})
        db.add(row)
        db.flush()
        audit(db, actor, 'tool_package.publish', 'tool-packages/' + row.id, [])
        return view(row)


@router.get('/machines/{id}/tool-jobs')
def jobs(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        if not db.get(Machine, id):
            raise Problem(404, 'not_found', '机器不存在')
        rows = list(db.scalars(select(ToolJob).where(ToolJob.machine_id == id).order_by(ToolJob.created_at.desc()).limit(20)))
        for row in rows:
            expire(db, row)
        return [view(row) for row in rows]


@router.post('/machines/{id}/tool-jobs', status_code=202)
def start(id: str, payload: JobInput, request: Request, background: BackgroundTasks, user=Depends(current_user)):
    settings = request.app.state.settings
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        machine = db.get(Machine, id, with_for_update=True)
        if not machine:
            raise Problem(404, 'not_found', '机器不存在')
        require_manage(actor, machine)
        if machine.archived or machine.maintenance:
            raise Problem(409, 'machine_unavailable', '机器已归档或处于维护状态')
        from dingofs_platform.performance.models import PerformanceRun, ACTIVE
        if db.scalar(select(PerformanceRun.id).where(PerformanceRun.machine_id == id, PerformanceRun.state.in_(ACTIVE))):
            raise Problem(409, 'performance_busy', '该机器有性能任务正在运行或状态未确认，请先结束性能任务')
        if not machine.ssh_password_ciphertext:
            raise Problem(422, 'ssh_password_missing', '请先配置机器 SSH 密码')
        for previous in db.scalars(select(ToolJob).where(ToolJob.machine_id == id, ToolJob.state == 'running')):
            expire(db, previous)
            if previous.state == 'running':
                raise Problem(409, 'tools_busy', '该机器已有工具任务正在执行')
        source_config = None
        options = None
        if payload.action == 'auto_install':
            if not payload.tool or payload.package_id:
                raise Problem(422,'invalid_request','请选择工具')
            source = get_source(db)
            source_machine = db.get(Machine,source.machine_id)
            if not source_machine or source_machine.archived or source_machine.maintenance or not source_machine.ssh_password_ciphertext:
                raise Problem(422,'source_unavailable','平台工具来源机器不可用')
            options = {key:getattr(source,key) for key in ('directory','image','allow_cached')}
            options['tool'] = payload.tool
            options['source_machine_id'] = source.machine_id
            source_config = SSHConfig(source_machine.address,source_machine.ssh_port,source_machine.ssh_user,
                decrypt_password(source_machine.ssh_password_ciphertext,settings.credential_encryption_key))
        elif payload.action == 'install':
            if not payload.package_id or not db.get(ToolPackage, payload.package_id):
                raise Problem(422, 'package_missing', '请选择有效的工具包')
        elif payload.package_id:
            raise Problem(422, 'invalid_request', '检查工具时无需指定工具包')
        config = SSHConfig(machine.address, machine.ssh_port, machine.ssh_user,
                           decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key))
        row = ToolJob(machine_id=id, creator_id=actor.id, package_id=payload.package_id, action=payload.action, options=options,
                      deadline=datetime.now(timezone.utc)+timedelta(seconds=settings.tool_deploy_timeout+30))
        db.add(row)
        db.flush()
        audit(db, actor, 'machine_tools.' + payload.action, 'machines/' + id, [])
        result = view(row)
    background.add_task(run_job, request.app, result['id'], config, source_config)
    return result
