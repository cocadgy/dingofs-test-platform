"""Controller-side port reservations and one-time, revision-bound creation plans."""
from copy import deepcopy
from datetime import timedelta
from sqlalchemy import select
from dingofs_platform.errors import Problem
from .models import ManagedResource, ResourceOperation
from .views import now, ACTIVE


def reserved_ports(db, member):
    ports = set()
    for resource in db.scalars(select(ManagedResource).where(ManagedResource.kind == "cache", ManagedResource.state.in_(("planned", "pending", "running", "partial")))):
        if resource.state in ("planned", "pending"):
            operations = list(db.scalars(select(ResourceOperation).where(ResourceOperation.resource_id == resource.id)))
            if not any(op.expires_at > now() and (op.state in ACTIVE or op.action == "cache.plan" and op.state == "succeeded" and op.created_at > now()-timedelta(minutes=10)) for op in operations):
                continue
        for other in resource.data.get("members", []):
            if other["machine_id"] == member["machine_id"] and other["member_id"] != member["member_id"]:
                ports.add(other["listen_port"])
    return ports


def reserve(db, resource, work):
    assigned = {}
    for item in work:
        member = deepcopy(item["record"])
        item["record"] = member
        ports = reserved_ports(db, member) | assigned.setdefault(member["machine_id"], set())
        if member.get("port_mode", "manual") == "auto":
            port = next((p for p in range(21000, 30000) if p not in ports), None)
            if port is None:
                raise Problem(409, "ports_exhausted", "自动端口范围 21000–29999 已无可用端口")
            member["listen_port"] = port
        elif member["listen_port"] in ports:
            raise Problem(409, "port_reserved", f"端口 {member['listen_port']} 已被平台其他成员或任务预留，请使用自动分配或更换端口")
        assigned[member["machine_id"]].add(member["listen_port"])
        member["planned_port"] = member["listen_port"]
        item["parameters"] = deepcopy(member)
    resource.data = {**resource.data, "members": [deepcopy(item["record"]) for item in work]}


def consume(db, actor, cluster, plan_id):
    from .execution import valid
    plan = db.get(ResourceOperation, plan_id)
    if (not plan or plan.action != "cache.plan" or plan.actor_id != actor.id
            or plan.cluster_id != cluster.id or plan.state != "succeeded"
            or plan.created_at <= now()-timedelta(minutes=10) or not valid(db, plan)):
        raise Problem(409, "plan_stale", "端口检查清单已失效或尚未完成，请重新检查")
    resource = db.get(ManagedResource, plan.resource_id)
    if not resource or resource.state != "planned":
        raise Problem(409, "plan_consumed", "该检查清单已用于创建，请查看原任务；重新创建需重新检查")
    resource.state = "pending"
    work = deepcopy(plan.steps)
    for item in work:
        item["action"] = "cache.create"
    return work, resource


def store_effective_port(db, op, cursor, port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port response")
    steps = deepcopy(op.steps)
    member = steps[cursor]["record"]
    # Concurrent plans may have probed the same port; only one reservation wins.
    if op.action == "cache.plan" and port in reserved_ports(db, member):
        raise ValueError("端口检查期间被其他任务预留，请重新检查")
    member["listen_port"] = port
    if op.action == "cache.plan":
        member["planned_port"] = port
    steps[cursor]["parameters"]["listen_port"] = port
    op.steps = steps
    resource = db.get(ManagedResource, op.resource_id)
    resource.data = {**resource.data, "members": [
        {**row, "listen_port": port, **({"planned_port": port} if op.action == "cache.plan" else {})}
        if row["member_id"] == member["member_id"] else row
        for row in resource.data["members"]
    ]}


def store_binary_info(db, op, cursor, info):
    if not isinstance(info, dict) or not str(info.get("path", "")).startswith("/") or len(info.get("sha256", "")) != 64:
        raise ValueError("程序检查没有返回有效路径和校验值")
    steps = deepcopy(op.steps)
    steps[cursor]["record"]["binary_info"] = info
    op.steps = steps
    resource = db.get(ManagedResource, op.resource_id)
    member_id = steps[cursor]["record"]["member_id"]
    resource.data = {**resource.data, "members": [
        {**row, "binary_info": info} if row["member_id"] == member_id else row
        for row in resource.data["members"]
    ]}


def retry_creation(db, actor, cluster, operation_id):
    from .execution import valid
    previous = db.get(ResourceOperation, operation_id)
    if (not previous or previous.action != "cache.create" or previous.actor_id != actor.id
            or previous.cluster_id != cluster.id or previous.state not in ("failed", "interrupted", "cancelled", "unknown")
            or not valid(db, previous)):
        raise Problem(409, "retry_invalid", "原创建任务不可重试，请刷新并核实状态")
    resource = db.get(ManagedResource, previous.resource_id)
    if not resource or resource.state not in ("partial", "unknown"):
        raise Problem(409, "retry_invalid", "缓存组当前状态不可重试")
    rows = {m["member_id"]: m for m in resource.data["members"]}
    work = []
    for original in previous.steps:
        member = rows[original["record"]["member_id"]]
        if member.get("process_state") == "running":
            continue
        item = deepcopy(original)
        item["record"] = deepcopy(member)
        work.append(item)
    if not work:
        raise Problem(409, "retry_empty", "没有需要重试的节点")
    resource.state = "pending"
    return work, resource
