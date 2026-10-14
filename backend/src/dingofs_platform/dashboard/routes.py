"""Single read-only snapshot for the resource home page."""

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from dingofs_platform.errors import Problem
from sqlalchemy import select

from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.inventory.models import Cluster, Machine, cluster_machines
from dingofs_platform.inventory.overview import overview as machine_overview

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def role_health(snapshot):
    roles = defaultdict(lambda: [0, 0])
    for service in snapshot.get("services", []):
        role = str(service.get("role", "unknown"))
        roles[role][0] += service.get("running_instances", 0)
        roles[role][1] += service.get("expected_instances", 0)
    return {key: {"running": value[0], "expected": value[1]}
            for key, value in sorted(roles.items())}


@router.get("")
def dashboard(request: Request, user=Depends(current_user)):
    monitor = getattr(request.app.state, "dashboard_monitor", None)
    probes, checks, progress = monitor.snapshot() if monitor else ({}, {}, {"running": False, "completed": 0, "total": 0, "error": None})
    with get_db(request) as db:
        machines = list(db.scalars(select(Machine).order_by(Machine.name, Machine.id)))
        clusters = list(db.scalars(select(Cluster).order_by(Cluster.name, Cluster.id)))
        machine_names = {row.id: row.name for row in machines}
        links = defaultdict(list)
        for cluster_id, machine_id in db.execute(
            select(cluster_machines.c.cluster_id, cluster_machines.c.machine_id)
        ):
            links[machine_id].append(cluster_id)
        items = []
        for row in machines:
            data = machine_overview({key: getattr(row, key) for key in (
                "id", "name", "address", "archived", "collection_status",
                "hardware_info", "last_attempt_info", "last_success_at",
                "last_attempt_at", "collection_expires_at",
            )})
            data.update(creator_id=row.creator_id, maintenance=row.maintenance,
                        probe=probes.get(row.id), cluster_ids=links.get(row.id, []))
            items.append(data)
        cluster_items = []
        for row in clusters:
            check = checks.get(row.id)
            snapshot = (check or {}).get("snapshot") or row.status_snapshot or {}
            cluster_items.append({
                "id": row.id, "name": row.name, "external_name": row.external_name,
                "creator_id": row.creator_id, "archived": row.archived,
                "binding_state": row.binding_state,
                "management_machine_id": row.management_machine_id,
                "machine_name": machine_names.get(row.management_machine_id, ""),
                "os_user": row.os_user, "state": (check or {}).get("state") or snapshot.get("state", "unknown"),
                "last_success_at": (check or {}).get("checked_at") if (check or {}).get("snapshot") else row.status_success_at,
                "last_attempt_at": (check or {}).get("checked_at") or row.status_attempt_at,
                "last_error": check.get("error") if check is not None else (
                    (row.status_error_code or row.status_attempt_state)
                    if row.status_attempt_state not in ("succeeded", "never") else None
                ),
                "service_count": snapshot.get("service_count"),
                "running_instances": snapshot.get("running_instances"),
                "expected_instances": snapshot.get("expected_instances"),
                "roles": role_health(snapshot),
                "services": [
                    {"id": s.get("id"), "role": s.get("role"), "state": s.get("state")}
                    for s in snapshot.get("services", []) if s.get("state") != "running"
                ][:5],
            })
    return {"machines": items, "clusters": cluster_items,
            "generated_at": datetime.now(timezone.utc).isoformat(), "progress": progress}


@router.post("/refresh")
def refresh(request: Request, user=Depends(current_user)):
    monitor = getattr(request.app.state, "dashboard_monitor", None)
    if not monitor or not request.app.state.settings.dashboard_monitor_enabled:
        raise Problem(503, "monitor_disabled", "后台状态检查未启用")
    return {"started": monitor.trigger()}
