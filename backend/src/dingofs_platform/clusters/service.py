from sqlalchemy import select
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.service import lock_inventory, serialize, audit
from .operations import (
    load_owned,
    check_target,
    now,
    current_session,
    start_operation,
    run_operation,
    expired,
)
from .models import ClusterOperation
from dingofs_platform.inventory.permissions import require_manage


def attempt_state(db, c):
    if c.status_attempt_state not in ("pending", "running", "needs_password"):
        return c.status_attempt_state
    latest = db.scalar(
        select(ClusterOperation)
        .where(
            ClusterOperation.cluster_id == c.id,
            ClusterOperation.kind == "status",
            ClusterOperation.cluster_revision == c.revision,
        )
        .order_by(ClusterOperation.created_at.desc())
        .limit(1)
    )
    if latest and expired(latest):
        return "interrupted"
    return latest.state if latest else c.status_attempt_state


def detail_view(db, c):
    result = serialize(db, "clusters", c)
    m = db.get(Machine, c.management_machine_id)
    result.update(machine_name=m.name, machine_address=m.address, ssh_user=m.ssh_user)
    result["status_attempt_state"] = attempt_state(db, c)
    hosts = {row["host"] for row in (c.status_snapshot or {}).get("services", [])}
    machines = (
        list(db.scalars(select(Machine).where(Machine.archived == False)))
        if hosts
        else []
    )
    result["node_links"] = {}
    for host in hosts:
        matches = [m.id for m in machines if m.address.lower() == host.lower()]
        if len(matches) == 1:
            result["node_links"][host] = matches[0]
    return result


def refresh(request, actor, id, revision, kind="status"):
    with get_db(request) as db:
        c = db.get(Cluster, id)
        if not c:
            raise Problem(404, "not_found", "集群不存在")
        m = db.get(Machine, c.management_machine_id)
        args = dict(
            kind=kind,
            machine_id=m.id,
            machine_revision=m.revision,
            target_user=c.os_user,
            cluster_id=c.id,
            cluster_revision=revision,
        )
    return start_operation(request, actor, **args)


def initial_refresh(request, actor, ids):
    for id in ids:
        try:
            with get_db(request) as db:
                revision = db.get(Cluster, id).revision
            op, new = refresh(request, actor, id, revision)
            if new:
                run_operation(request, op["id"])
        except Problem:
            # The imported resource remains visible; an explicit refresh can retry.
            continue


def discovery_for_import(db, request, actor, id):
    current_session(db, request, actor)
    op = load_owned(db, id, actor)
    if (
        op.kind != "discover"
        or op.state != "succeeded"
        or op.expires_at <= now()
        or not check_target(db, op)
    ):
        raise Problem(409, "discovery_stale", "发现结果已失效，请重新发现")
    return op


def import_clusters(request, actor, id, names):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = discovery_for_import(db, request, actor, id)
        if not set(names) <= set(op.result["names"]):
            raise Problem(422, "invalid_selection", "只能导入本次发现的集群")
        identity = op.result["identity"]
        config_dir = identity["home"].rstrip("/") + "/.dingo"
        created = []
        existing = []
        confirmation = []
        for name in dict.fromkeys(names):
            candidates = list(
                db.scalars(
                    select(Cluster).where(
                        Cluster.management_machine_id == op.machine_id,
                        Cluster.os_user == op.target_user,
                        Cluster.external_name == name,
                    )
                )
            )
            matches = [c for c in candidates if c.config_dir == config_dir]
            if (
                len(matches) == 1
                and len(candidates) == 1
                and not matches[0].archived
                and matches[0].binding_state == "verified"
            ):
                c = matches[0]
                if c.binding_state != "verified":
                    c.binding_state = "verified"
                    c.execution_home = identity["home"]
                    c.resolved_dingo_path = identity["dingo_path"]
                    c.revision += 1
                existing.append(dict(id=c.id, name=c.name))
                continue
            if candidates:
                confirmation.append(
                    dict(
                        name=name,
                        candidates=[
                            dict(
                                id=c.id,
                                name=c.name,
                                config_dir=c.config_dir,
                                archived=c.archived,
                                revision=c.revision,
                            )
                            for c in candidates
                        ],
                    )
                )
                continue
            c = Cluster(
                name=name,
                creator_id=actor.id,
                external_name=name,
                management_machine_id=op.machine_id,
                os_user=op.target_user,
                dingo_path=identity["dingo_path"],
                config_dir=config_dir,
                credential_ref="",
                binding_state="verified",
                execution_home=identity["home"],
                resolved_dingo_path=identity["dingo_path"],
            )
            db.add(c)
            db.flush()
            created.append(dict(id=c.id, name=c.name))
            audit(db, actor, "cluster_import", "clusters/" + c.id, [])
        return dict(created=created, existing=existing, needs_confirmation=confirmation)


def rebind(request, actor, id, payload):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        op = discovery_for_import(db, request, actor, payload.discovery_id)
        c = db.get(Cluster, id)
        if not c or c.archived:
            raise Problem(422, "invalid_reference", "集群不存在或已归档")
        require_manage(actor, c)
        if c.revision != payload.base_revision:
            raise Problem(409, "revision_conflict", "集群配置已更新")
        if payload.name not in op.result["names"]:
            raise Problem(422, "invalid_selection", "本次未发现该集群")
        identity = op.result["identity"]
        directory = identity["home"].rstrip("/") + "/.dingo"
        conflict = db.scalar(
            select(Cluster).where(
                Cluster.id != id,
                Cluster.management_machine_id == op.machine_id,
                Cluster.os_user == op.target_user,
                Cluster.config_dir == directory,
                Cluster.external_name == payload.name,
            )
        )
        if conflict:
            raise Problem(409, "binding_conflict", "此入口已由另一个集群登记使用")
        c.management_machine_id = op.machine_id
        c.os_user = op.target_user
        c.external_name = payload.name
        c.config_dir = directory
        c.execution_home = identity["home"]
        c.resolved_dingo_path = identity["dingo_path"]
        c.binding_state = "verified"
        c.revision += 1
        c.status_snapshot = None
        c.status_success_at = None
        c.status_output = None
        c.status_attempt_state = "never"
        c.status_error_code = None
        audit(db, actor, "cluster_rebind", "clusters/" + id, [])
        db.flush()
        return detail_view(db, c)
