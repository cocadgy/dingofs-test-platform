from datetime import datetime, timezone
from pathlib import Path
from .models import ToolJob, ToolPackage
from .bundle import inspect_bundle
from .transport import execute
from dingofs_platform.errors import Problem
from dingofs_platform.operations.leases import (tool_requests, ensure_leases, lock_keys,
    release_verified, completion_evidence)


def view(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != 'manifest'}


def expire(db, row):
    if row.state == 'running' and row.deadline <= datetime.now(timezone.utc):
        row.state = 'interrupted'
        row.phase = '任务中断或超时'
        row.log += '\n任务未返回确定结果，请重新检查工具状态；不会自动重试安装。\n'


def run_job(app, id, config, source_config=None):
    factory = app.state.session_factory
    requests = []
    owner = 'tool:' + id
    remote_attempted = False

    def report(phase=None, progress=None, message=None):
        with factory.begin() as db:
            row = db.get(ToolJob, id, with_for_update=True)
            if row.state != 'running':
                raise RuntimeError('任务已结束')
            if phase:
                row.phase = phase
            if progress is not None:
                row.progress = max(row.progress, progress)
            if message:
                row.log = (row.log + message)[-131072:]

    try:
        with factory.begin() as db:
            row = db.get(ToolJob, id)
            if not row or row.state != 'running':
                return
            requests = tool_requests(row.machine_id, row.action, row.options)
            lock_keys(db, requests)
            row = db.get(ToolJob, id, with_for_update=True, populate_existing=True)
            if row.state != 'running':
                return
            if not ensure_leases(db, owner, requests).acquired:
                raise Problem(409, 'operation_conflict', '目标资源被其他操作占用或远端结果尚未确认')
            package = db.get(ToolPackage, row.package_id) if row.package_id else None
        bundle = None
        if package:
            report(phase='校验平台工具包')
            bundle = inspect_bundle(app.state.settings.tool_bundle_root, package.directory)
            if bundle['digest'] != package.digest:
                raise ValueError('平台工具包已改变，请重新登记新版本')
        transport = getattr(app.state, 'tool_transport', execute)
        remaining = int((row.deadline - datetime.now(timezone.utc)).total_seconds()) - 30
        if remaining <= 0:
            raise TimeoutError('工具包校验超时，请重新检查工具状态')
        if row.action == 'auto_install':
            from .automatic import deploy
            automatic = getattr(app.state, 'tool_automatic_transport', deploy)
            remote_attempted = True
            result = automatic(config, source_config, row.options, remaining, report)
        else:
            remote_attempted = True
            result = transport(config, bundle, app.state.settings.tool_bundle_root, remaining, report)
        with factory.begin() as db:
            lock_keys(db, requests)
            row = db.get(ToolJob, id, with_for_update=True)
            if row.state == 'running':
                row.state, row.phase, row.progress, row.result = 'success', '完成', 100, result
            release_verified(db, owner, completion_evidence(owner, requests))
    except Exception as exc:
        # Passwords are never placed in commands/logs or persisted in a job.
        message = exc.message if isinstance(exc, Problem) else str(exc)
        message = message.replace(config.password, '[REDACTED]') if config.password else message
        if source_config and source_config.password:
            message = message.replace(source_config.password, '[REDACTED]')
        with factory.begin() as db:
            lock_keys(db, requests)
            row = db.get(ToolJob, id, with_for_update=True)
            if row.state == 'running':
                row.state, row.phase = 'failed', '失败'
                row.result = {'error_message': message or type(exc).__name__}
                row.log = (row.log + '\n' + message)[-131072:]
            if not remote_attempted:
                release_verified(db, owner, completion_evidence(owner, requests))
