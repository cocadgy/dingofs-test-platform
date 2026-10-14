from datetime import datetime, timezone
from pathlib import Path
from .models import ToolJob, ToolPackage
from .bundle import inspect_bundle
from .transport import execute


def view(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != 'manifest'}


def expire(db, row):
    if row.state == 'running' and row.deadline <= datetime.now(timezone.utc):
        row.state = 'interrupted'
        row.phase = '任务中断或超时'
        row.log += '\n任务未返回确定结果，请重新检查工具状态；不会自动重试安装。\n'


def run_job(app, id, config, source_config=None):
    factory = app.state.session_factory

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
        with factory() as db:
            row = db.get(ToolJob, id)
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
            result = automatic(config, source_config, row.options, remaining, report)
        else:
            result = transport(config, bundle, app.state.settings.tool_bundle_root, remaining, report)
        with factory.begin() as db:
            row = db.get(ToolJob, id, with_for_update=True)
            if row.state == 'running':
                row.state, row.phase, row.progress, row.result = 'success', '完成', 100, result
    except Exception as exc:
        # Passwords are never placed in commands/logs or persisted in a job.
        message = str(exc).replace(config.password, '[REDACTED]') if config.password else str(exc)
        if source_config and source_config.password:
            message = message.replace(source_config.password, '[REDACTED]')
        with factory.begin() as db:
            row = db.get(ToolJob, id, with_for_update=True)
            if row.state == 'running':
                row.state, row.phase = 'failed', '失败'
                row.result = {'error_message': message or type(exc).__name__}
                row.log = (row.log + '\n' + message)[-131072:]
