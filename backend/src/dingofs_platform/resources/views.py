from datetime import datetime, timezone
from sqlalchemy import select
from dingofs_platform.inventory.models import Machine, Cluster
from dingofs_platform.operations.leases import LeaseRequest
from dingofs_platform.errors import Problem
from .models import ResourceOperation, ManagedResource
from .safety import redact
from .commands import is_mutating

ACTIVE = ("pending", "running", "needs_password")
MESSAGES = {
    "operation_conflict": "目标资源被其他操作占用或远端结果尚未确认",
    "retry_unverified": "重试链已有后续任务或远端结果未确认，请查看最新任务并先复核",
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
        from .bulk_create import finish_mount_batch
        finish_mount_batch(db, op)
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


def _step_results(db, op):
    result = redact(op.result, show_storage_keys=op.action == "fs.get")
    if not isinstance(result, dict) or not isinstance(result.get("steps"), list):
        return result
    for index, row in enumerate(result["steps"]):
        if not isinstance(row, dict):
            continue
        planned = op.steps[index] if index < len(op.steps) else {}
        mid = row.get("machine_id") or planned.get("machine_id")
        if planned.get("machine_id") != mid:
            planned = next((s for s in op.steps if s.get("machine_id") == mid
                            and s.get("target_user") == row.get("target_user")), {})
        machine = db.get(Machine, mid) if db is not None and mid else None
        row["machine_name"] = planned.get("machine_name") or getattr(machine, "name", None)
        row["machine_address"] = planned.get("machine_address") or getattr(machine, "address", None)
        row["target_user"] = row.get("target_user") or planned.get("target_user")
    return result


def operation_view(db, op, *, private=False):
    expire(db, op)
    step = op.steps[min(op.cursor, len(op.steps) - 1)] if op.steps else {}
    machine = db.get(Machine, step.get("machine_id")) if step else None
    return dict(
        id=op.id,
        cluster_id=op.cluster_id,
        creator_id=op.actor_id,
        action=op.action,
        state=op.state,
        payload=redact(op.parameters),
        result=_step_results(db, op),
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
        if op.state in ACTIVE and op.kind not in ("status", "topology"):
            raise Problem(409, "cluster_busy", "此集群有进行中的操作，请等待完成")


def lease_requests(db, cid, action, parameters, *, steps=None, actor=None):
    """Resolve mutation hosts before inventory locks, from server-owned records.

    Cluster RPCs only share their control host runtime. A common control host
    does not make unrelated clusters mutually exclusive.
    """
    preparation = action in ('cache.plan', 'mount.plan')
    if preparation:
        # The catalog labels plans read-only, but TAG plans upload/install a
        # binary. Resolve only those actual mutation targets, not path checks.
        if steps is not None:
            steps = [step for step in steps if step.get('record', {}).get('binary_source') == 'tag']
            if not steps:
                return []
        else:
            members = parameters.get('members' if action == 'cache.plan' else 'clients', [])
            members = [member for member in members if member.get('binary_source') == 'tag']
            if not members:
                return []
            parameters = {'members': members}
    elif not is_mutating(action):
        return []
    cluster = db.get(Cluster, cid)
    requests = [LeaseRequest('cluster:' + cid)]
    if cluster:
        requests.append(LeaseRequest('runtime:' + cluster.management_machine_id, 'shared'))
    local = preparation or action.startswith('mount.') or action in ('cache.create', 'cache.stop', 'trash.restore')
    if not local:
        return requests
    ids = set()
    def collect(value):
        if isinstance(value, dict):
            if value.get('machine_id'):
                ids.add(value['machine_id'])
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    if steps is not None:
        for work in steps:
            if work['action'] not in ('cache.verify_members', 'cache.wait_offline'):
                ids.add(work['machine_id'])
    else:
        collect(parameters)
        resource_ids = list(parameters.get('resource_ids', []))
        if parameters.get('resource_id'): resource_ids.append(parameters['resource_id'])
        member_ids = set(parameters.get('member_ids', [])) if action == 'cache.stop' else set()
        for rid in resource_ids:
            resource = db.get(ManagedResource, rid)
            if resource and resource.cluster_id == cid:
                collect(resource.data)
                if resource.data.get('origin') == 'external':
                    member_ids.update(m['member_id'] for m in resource.data.get('members', []))
        for field in ('plan_id', 'retry_operation_id'):
            previous = db.get(ResourceOperation, parameters[field]) if parameters.get(field) else None
            if previous and previous.cluster_id == cid:
                collect(previous.steps)
        if member_ids:
            matched = set()
            for resource in db.scalars(select(ManagedResource).where(ManagedResource.cluster_id == cid,
                                        ManagedResource.kind == 'cache', ManagedResource.state != 'deleted')):
                for member in resource.data.get('members', []):
                    if member.get('member_id') in member_ids and member.get('origin') != 'external' and member.get('machine_id'):
                        collect(member); matched.add(member['member_id'])
            if member_ids - matched and actor and cluster:
                from .external_cache import resolve_members
                for target in resolve_members(db, actor, cluster, sorted(member_ids - matched)).values():
                    ids.add(target['machine_id'])
        if action == 'trash.restore' and cluster:
            ids.add(cluster.management_machine_id)
    for mid in sorted(ids):
        requests.extend([LeaseRequest('machine:' + mid), LeaseRequest('runtime:' + mid,
                         'exclusive' if preparation else 'shared')])
    return requests


def verified_retry_root(db, cid, action, parameters, actor_id, *, current_operation_id=None):
    """Keep an exact failed create/retry chain under its original lease owner.

    A transport exception/unknown outcome never authorizes retry. remote_ended
    is written by our execution adapter only after a valid command response;
    browser parameters cannot supply it. The existing plan consumers separately
    select only unfinished members and verify their immutable saved targets.
    """
    previous_id = parameters.get('retry_operation_id')
    if not previous_id:
        return None
    from dingofs_platform.auth.users import lock_accounts
    # Serialize descendant inspection with API creation and worker transitions.
    # This is the first lock in the accounts -> leases -> inventory hierarchy.
    lock_accounts(db)
    from .execution import valid
    seen = set()
    while previous_id:
        if previous_id in seen or len(seen) >= 32:
            raise Problem(409, 'retry_invalid', '重试任务链无效')
        seen.add(previous_id)
        previous = db.get(ResourceOperation, previous_id)
        if (not previous or previous.actor_id != actor_id or previous.cluster_id != cid
                or previous.action != action or action not in ('cache.create', 'mount.create')
                or not valid(db, previous)):
            raise Problem(409, 'retry_invalid', '原任务与当前账号、集群或计划不匹配')
        results = (previous.result or {}).get('steps', [])
        if (previous.state != 'failed' or previous.error_code not in ('query_failed', 'batch_failed')
                or not results or not all(result.get('remote_ended') is True for result in results)):
            raise Problem(409, 'retry_unverified', '原任务远端结果未确认，请先复核后再重试')
        previous_id = previous.parameters.get('retry_operation_id')
    lineage = seen | ({current_operation_id} if current_operation_id else set())
    # A valid retry extends the latest chain, never forks an older ancestor.
    # Any branch leaves this chain at an immediate child, so checking children
    # of every ancestor also catches deeper unknown descendants. The executing
    # operation itself is allowed; pending siblings and its children are not.
    descendants = db.scalars(select(ResourceOperation.id).where(
        ResourceOperation.cluster_id == cid, ResourceOperation.action == action,
        ResourceOperation.parameters['retry_operation_id'].as_string().in_(lineage)))
    if any(candidate not in lineage for candidate in descendants):
        raise Problem(409, 'retry_unverified', MESSAGES['retry_unverified'])
    return previous
