from sqlalchemy import select, delete, text
from dingofs_platform.inventory.models import (
    Machine,
    ManagementContext,
    Cluster,
    Environment,
    cluster_machines,
    environment_machines,
)
from dingofs_platform.errors import Problem
from dingofs_platform.audit.models import AuditEvent

MODELS = {
    "machines": Machine,
    "management-contexts": ManagementContext,
    "clusters": Cluster,
    "environments": Environment,
}
LINKS = {
    "clusters": (cluster_machines, "cluster_id"),
    "environments": (environment_machines, "environment_id"),
}


def serialize(db, kind, row):
    data = {col.name: getattr(row, col.name) for col in row.__table__.columns}
    if kind in LINKS:
        table, key = LINKS[kind]
        data["machine_ids"] = list(
            db.scalars(select(table.c.machine_id).where(table.c[key] == row.id))
        )
    return data


def lock_inventory(db):
    # Serializes relationship mutations and archival, not future long-running jobs.
    db.execute(text("SELECT pg_advisory_xact_lock(7412081)"))


def active(db, model, id):
    row = db.get(model, id)
    if not row or row.archived:
        raise Problem(422, "invalid_reference", "关联资源不存在或已归档")
    return row


def validate_refs(db, kind, data):
    if kind == "management-contexts":
        active(db, Machine, data["machine_id"])
    if kind == "clusters":
        active(db, ManagementContext, data["context_id"])
    if kind == "environments":
        active(db, Cluster, data["cluster_id"])
    for mid in data.get("machine_ids", []):
        active(db, Machine, mid)


def check_archive(db, kind, id):
    queries = []
    if kind == "machines":
        queries = [
            select(ManagementContext.id).where(
                ManagementContext.machine_id == id, ManagementContext.archived == False
            ),
            select(Cluster.id)
            .join(cluster_machines, Cluster.id == cluster_machines.c.cluster_id)
            .where(cluster_machines.c.machine_id == id, Cluster.archived == False),
            select(Environment.id)
            .join(
                environment_machines,
                Environment.id == environment_machines.c.environment_id,
            )
            .where(
                environment_machines.c.machine_id == id, Environment.archived == False
            ),
        ]
    if kind == "management-contexts":
        queries = [
            select(Cluster.id).where(
                Cluster.context_id == id, Cluster.archived == False
            )
        ]
    if kind == "clusters":
        queries = [
            select(Environment.id).where(
                Environment.cluster_id == id, Environment.archived == False
            )
        ]
    if any(db.scalar(q.limit(1)) for q in queries):
        raise Problem(409, "resource_in_use", "资源仍被引用，不能归档")


def set_links(db, kind, row, ids):
    if kind not in LINKS:
        return
    table, key = LINKS[kind]
    db.execute(delete(table).where(table.c[key] == row.id))
    for mid in set(ids):
        db.execute(table.insert().values(**{key: row.id, "machine_id": mid}))


def audit(db, user, action, entity, fields):
    db.add(
        AuditEvent(
            actor=user.id,
            request_id=db.info.get("request_id", ""),
            action=action,
            entity=entity,
            detail={"fields": sorted(fields)},
        )
    )
