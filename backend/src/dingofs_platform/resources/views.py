from datetime import datetime, timezone
from sqlalchemy import select
from dingofs_platform.inventory.models import Machine
from dingofs_platform.errors import Problem
from .models import ResourceOperation, ManagedResource
from .safety import redact
from .commands import is_mutating

ACTIVE = ("pending", "running", "needs_password")
MESSAGES = {
    "python_missing": "目标用户环境中未找到 python3，无法核验并停止缓存进程",
    "batch_failed": "批量操作已完成，但部分目标失败，请查看逐项结果",
    "timeout": "操作超时，远端结果可能未知，请先核实状态后再操作",
    "interrupted": "操作中断，远端结果可能未知，请先核实状态",
    "stale": "账号、机器或集群配置已变化，请刷新后重新操作",
    "cancelled": "已取消后续步骤；已执行的步骤不会回滚，请核实远端状态",
    "query_failed": "命令执行失败，请查看步骤结果；部分步骤可能已经成功",
    "output_limit": "命令输出超过平台大小限制，结果未能完整返回",
    "worker_failed": "执行未完成，请核实机器环境及远端状态",
    "needs_password": "切换执行用户需要认证",
    "credential_unavailable": "SSH 或存储凭据不可用，请检查平台加密密钥和机器密码",
    "auth_limit": "认证次数已达上限，请重新发起操作",
}


def now():
    return datetime.now(timezone.utc)


def expire(db, op):
    if op.state in ACTIVE and op.expires_at <= now():
        op.state = "interrupted"
        op.error_code = "interrupted"
        op.secret_ciphertext = None
        op.challenge_digest = None
        if op.resource_id and is_mutating(op.action):
            resource = db.get(ManagedResource, op.resource_id)
            resource.state = "unknown"


def _operation_message(op):
    fallback = MESSAGES.get(op.error_code, op.error_code)
    if op.error_code != "query_failed" or not isinstance(op.result, dict):
        return fallback
    results = op.result.get("steps")
    # The cursor counts completed steps; a failed result is appended at that
    # index without advancing it. Do not reuse an earlier success message when
    # a transport/parsing failure did not produce a result for this step.
    if not isinstance(results, list) or not 0 <= op.cursor < len(results):
        return fallback
    failed_step = results[op.cursor]
    message = failed_step.get("message") if isinstance(failed_step, dict) else None
    if not isinstance(message, str) or not message.strip():
        return fallback
    message = message.strip()
    if message == "command output exceeded limit":
        message = MESSAGES["output_limit"]
    else:
        # Error summaries never opt in to fs.get's storage-key display.
        message = redact(message)
    if op.cursor > 0:
        message += "；部分步骤可能已经成功，请查看步骤结果"
    return message


def operation_view(db, op, *, private=False):
    expire(db, op)
    step = op.steps[min(op.cursor, len(op.steps) - 1)] if op.steps else {}
    machine = db.get(Machine, step.get("machine_id")) if step else None
    return dict(
        id=op.id,
        creator_id=op.actor_id,
        action=op.action,
        state=op.state,
        payload=redact(op.parameters),
        result=redact(op.result, show_storage_keys=op.action == "fs.get"),
        error_code=op.error_code,
        message=_operation_message(op),
        auth_account=op.auth_account if private else None,
        challenge=op.lease_token if private and op.state == "needs_password" else None,
        target_user=step.get("target_user"),
        machine_name=machine.name if machine else None,
        resource_id=op.resource_id,
        phase="waiting_offline" if step.get("action") == "cache.wait_offline" and op.state in ACTIVE else None,
        completed_steps=op.cursor,
        total_steps=len(op.steps),
        created_at=op.created_at.isoformat(),
        expires_at=op.expires_at.isoformat(),
    )


def resource_view(row):
    return dict(
        id=row.id,
        kind=row.kind,
        name=row.name,
        state=row.state,
        data=row.data,
        created_at=row.created_at.isoformat(),
    )


def check_busy(db, cid):
    from dingofs_platform.clusters.models import ClusterOperation

    for op in db.scalars(
        select(ResourceOperation).where(
            ResourceOperation.cluster_id == cid, ResourceOperation.state.in_(ACTIVE)
        )
    ):
        expire(db, op)
        if op.state in ACTIVE:
            raise Problem(409, "resource_busy", "此集群有进行中的资源操作，请等待完成")
    from dingofs_platform.clusters.operations import expire as expire_cluster

    for op in db.scalars(
        select(ClusterOperation).where(
            ClusterOperation.cluster_id == cid, ClusterOperation.state.in_(ACTIVE)
        )
    ):
        expire_cluster(op)
        if op.state in ACTIVE:
            raise Problem(409, "cluster_busy", "此集群有进行中的操作，请等待完成")
