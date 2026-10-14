"""Resolve remote targets from current inventory; never accept browser shell paths."""

import posixpath
from datetime import datetime, timezone
from sqlalchemy import select
from dingofs_platform.auth.models import Session, User
from dingofs_platform.auth.service import digest
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.permissions import can_manage
from dingofs_platform.resources.models import ManagedResource


def now():
    return datetime.now(timezone.utc)


def login(db, token):
    session = db.scalar(select(Session).where(Session.token_hash == digest(token)))
    actor = db.get(User, session.user_id) if session else None
    if not actor or actor.disabled or session.expires_at <= now():
        raise Problem(401, "unauthenticated", "请重新登录")
    return actor, session


def cluster(db, cid):
    c = db.get(Cluster, cid)
    if not c or c.archived:
        raise Problem(404, "not_found", "集群不存在或已归档")
    return c


def targets(db, c, actor):
    from dingofs_platform.inventory.host_identity import resolve_host

    services = []
    machines = {}
    management = db.get(Machine, c.management_machine_id)
    if management and not management.archived:
        machines[management.id] = management
    for s in (c.status_snapshot or {}).get("services", []):
        matches = resolve_host(db, s.get("host", ""))
        m = matches[0] if len(matches) == 1 else None
        if m:
            machines[m.id] = m
        services.append(
            {
                "id": s["id"],
                "role": s.get("role", ""),
                "host": s.get("host", ""),
                "log_dir": s.get("log_dir", ""),
                "machine_id": m.id if m else None,
                "can_read_logs": bool(
                    m and can_manage(actor, c) and can_manage(actor, m)
                ),
                "match_state": "matched"
                if m
                else ("ambiguous" if matches else "missing"),
            }
        )
    return {
        "items": [
            {
                "machine_id": m.id,
                "name": m.name,
                "address": m.address,
                "ssh_user": m.ssh_user,
                "ssh_port": m.ssh_port,
                "service_ids": [s["id"] for s in services if s["machine_id"] == m.id],
                "can_read_logs": can_manage(actor, c) and can_manage(actor, m),
            }
            for m in machines.values()
        ],
        "services": services,
    }


def log_target(db, c, actor, service_id):
    if isinstance(service_id, str) and service_id.startswith("mount:"):
        resource = db.get(ManagedResource, service_id[6:])
        if (not resource or resource.cluster_id != c.id or resource.kind != "mount"
                or resource.state in ("deleted", "planned")):
            raise Problem(404, "not_found", "挂载记录不存在")
        data = resource.data or {}
        m = db.get(Machine, data.get("machine_id"))
        if not m or m.archived or not (can_manage(actor, c) and can_manage(actor, m)):
            raise Problem(403, "forbidden", "无权读取此客户端日志")
        root = data.get("log_dir")
        user = data.get("target_user")
        if (not isinstance(root, str) or not root.startswith("/")
                or not posixpath.normpath(root).strip("/") or len(root) > 4096
                or any(ord(ch) < 32 for ch in root)
                or not isinstance(user, str) or not user):
            raise Problem(422, "invalid_log_directory", "客户端日志目录不可用")
        return m, posixpath.normpath(root), user
    candidates = [s for s in targets(db, c, actor)["services"] if s["id"] == service_id]
    if len(candidates) != 1:
        raise Problem(422, "service_missing", "服务不在当前集群状态中，请刷新集群状态")
    s = candidates[0]
    if s["match_state"] != "matched":
        raise Problem(
            409, "host_" + s["match_state"], "服务主机未唯一匹配，请配置机器别名"
        )
    if not s["can_read_logs"]:
        raise Problem(
            403, "forbidden", "仅管理员或同时拥有此集群和机器的用户可查看日志"
        )
    root = s["log_dir"]
    if (
        not isinstance(root, str)
        or not root.startswith("/")
        or not posixpath.normpath(root).strip("/")
        or len(root) > 4096
        or any(ord(ch) < 32 for ch in root)
    ):
        raise Problem(422, "invalid_log_directory", "此服务没有可用的日志目录")
    return db.get(Machine, s["machine_id"]), posixpath.normpath(root), c.os_user


def terminal_target(db, c, actor, mid):
    if actor.role != "admin":
        raise Problem(403, "forbidden", "网页终端仅限管理员")
    if mid not in {m["machine_id"] for m in targets(db, c, actor)["items"]}:
        raise Problem(403, "invalid_target", "只能连接此集群的管理机器或已匹配服务机器")
    return db.get(Machine, mid)


def valid(db, row):
    actor = db.get(User, row.actor_id)
    session = db.get(Session, row.login_session_id)
    if (
        not actor
        or actor.disabled
        or not session
        or session.user_id != row.actor_id
        or session.expires_at <= now()
    ):
        return False
    c = db.get(Cluster, row.cluster_id) if row.cluster_id else None
    m = db.get(Machine, row.machine_id)
    if (
        not m
        or m.archived
        or m.revision != row.machine_revision
        or row.expires_at <= now()
    ):
        return False
    try:
        if row.kind == "terminal" and c is None and row.cluster_id is None:
            return can_manage(actor, m) and m.ssh_user == row.target_user
        if not c or c.archived or c.revision != row.cluster_revision:
            return False
        if row.kind == "terminal":
            return terminal_target(db, c, actor, m.id).ssh_user == row.target_user
        machine, root, target_user = log_target(db, c, actor, row.service_id)
        return (
            machine.id == m.id and root == row.log_root and target_user == row.target_user
        )
    except Problem:
        return False
