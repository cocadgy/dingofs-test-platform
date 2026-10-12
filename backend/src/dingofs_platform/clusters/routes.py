from fastapi import APIRouter, Depends, Request, BackgroundTasks, Query
from sqlalchemy import select, func
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.service import lock_inventory, check_archive, audit
from dingofs_platform.inventory.permissions import require_manage
from .schemas import (
    DiscoverInput,
    ControlInput,
    AuthInput,
    ImportInput,
    RevisionInput,
    EditInput,
    RebindInput,
    OperationView,
    ClusterList,
    ClusterDetailView,
    ImportResult,
)
from .operations import (
    start_operation,
    run_operation,
    load_owned,
    view,
    resume_operation,
    cancel_operation,
    current_session,
)
from .service import (
    import_clusters,
    detail_view,
    refresh,
    initial_refresh,
    rebind,
    attempt_state,
)

router = APIRouter(prefix="/api/v1", tags=["clusters"])


@router.post("/cluster-discoveries", status_code=202, response_model=OperationView)
def discover(
    payload: DiscoverInput,
    request: Request,
    background: BackgroundTasks,
    user=Depends(current_user),
):
    op, new = start_operation(request, user, kind="discover", **payload.model_dump())
    if new:
        background.add_task(run_operation, request, op["id"])
    return op


@router.get("/cluster-operations/{id}", response_model=OperationView)
def operation(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        return view(db, load_owned(db, id, user))


@router.post("/cluster-operations/{id}/authenticate", response_model=OperationView)
def authenticate(
    id: str, payload: AuthInput, request: Request, user=Depends(current_user)
):
    return resume_operation(
        request, user, id, payload.challenge, payload.password.get_secret_value()
    )


@router.post("/cluster-operations/{id}/cancel", response_model=OperationView)
def cancel(id: str, request: Request, user=Depends(current_user)):
    return cancel_operation(request, user, id)


@router.post("/cluster-discoveries/{id}/import", response_model=ImportResult)
def importing(
    id: str,
    payload: ImportInput,
    request: Request,
    background: BackgroundTasks,
    user=Depends(current_user),
):
    result = import_clusters(request, user, id, payload.names)
    background.add_task(
        initial_refresh,
        request,
        user,
        [r["id"] for r in result["created"] + result["existing"]],
    )
    return result


@router.get("/clusters/overview", response_model=ClusterList)
def overview(
    request: Request,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
):
    with get_db(request) as db:
        rows = db.execute(
            select(Cluster, Machine)
            .join(Machine, Cluster.management_machine_id == Machine.id)
            .order_by(Cluster.created_at, Cluster.id)
            .offset(offset)
            .limit(limit)
        ).all()
        items = []
        for c, m in rows:
            snapshot = c.status_snapshot or {}
            items.append(
                dict(
                    id=c.id,
                    name=c.name,
                    external_name=c.external_name,
                    machine_name=m.name,
                    machine_address=m.address,
                    os_user=c.os_user,
                    archived=c.archived,
                    binding_state=c.binding_state,
                    cluster_kind=snapshot.get("cluster_kind"),
                    state=snapshot.get("state", "unknown"),
                    node_count=snapshot.get("node_count"),
                    service_count=snapshot.get("service_count"),
                    running_instances=snapshot.get("running_instances"),
                    expected_instances=snapshot.get("expected_instances"),
                    status_success_at=c.status_success_at,
                    status_attempt_state=attempt_state(db, c),
                    revision=c.revision,
                    creator_id=c.creator_id,
                )
            )
        return dict(
            items=items, total=db.scalar(select(func.count()).select_from(Cluster))
        )


@router.get("/clusters/{id}", response_model=ClusterDetailView)
def detail(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        c = db.get(Cluster, id)
        if not c:
            raise Problem(404, "not_found", "集群不存在")
        return detail_view(db, c)


@router.post(
    "/clusters/{id}/refresh-status", status_code=202, response_model=OperationView
)
def refresh_status(
    id: str,
    payload: RevisionInput,
    request: Request,
    background: BackgroundTasks,
    user=Depends(current_user),
):
    op, new = refresh(request, user, id, payload.base_revision)
    if new:
        background.add_task(run_operation, request, op["id"])
    return op


@router.post("/clusters/{id}/control", status_code=202, response_model=OperationView)
def control(
    id: str,
    payload: ControlInput,
    request: Request,
    background: BackgroundTasks,
    user=Depends(current_user),
):
    if not payload.confirmed:
        raise Problem(422, "confirmation_required", "请先确认操作")
    op, new = refresh(
        request,
        user,
        id,
        payload.base_revision,
        kind=payload.action,
        parameters={"scope": payload.scope, "target": payload.target},
    )
    if new:
        background.add_task(run_operation, request, op["id"])
    return op


@router.get("/clusters/{id}/topology")
def stored_topology(id: str, request: Request, user=Depends(current_user)):
    from .models import ClusterOperation

    with get_db(request) as db:
        c = db.get(Cluster, id)
        if not c:
            raise Problem(404, "not_found", "集群不存在")
        op = db.scalar(
            select(ClusterOperation)
            .where(
                ClusterOperation.cluster_id == id,
                ClusterOperation.cluster_revision == c.revision,
                ClusterOperation.kind == "topology",
                ClusterOperation.state == "succeeded",
            )
            .order_by(ClusterOperation.finished_at.desc())
            .limit(1)
        )
        return {
            "stdout": op.result.get("stdout", "") if op and op.result else None,
            "collected_at": op.finished_at if op else None,
        }


@router.post("/clusters/{id}/topology", status_code=202, response_model=OperationView)
def topology(
    id: str,
    payload: RevisionInput,
    request: Request,
    background: BackgroundTasks,
    user=Depends(current_user),
):
    op, new = refresh(request, user, id, payload.base_revision, kind="topology")
    if new:
        background.add_task(run_operation, request, op["id"])
    return op


@router.post("/clusters/{id}/rebind", response_model=ClusterDetailView)
def binding(
    id: str, payload: RebindInput, request: Request, user=Depends(current_user)
):
    return rebind(request, user, id, payload)


@router.patch("/clusters/{id}", response_model=ClusterDetailView)
def edit(id: str, payload: EditInput, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        current_session(db, request, user)
        c = db.get(Cluster, id)
        if not c:
            raise Problem(404, "not_found", "集群不存在")
        require_manage(user, c)
        if c.revision != payload.base_revision:
            raise Problem(409, "revision_conflict", "集群配置已更新")
        if payload.archived is True:
            check_archive(db, "clusters", id)
        if (
            payload.archived is False
            and db.get(Machine, c.management_machine_id).archived
        ):
            raise Problem(422, "invalid_reference", "执行机器已归档")
        if payload.name is not None:
            c.name = payload.name
        if payload.archived is not None:
            c.archived = payload.archived
        c.revision += 1
        audit(db, user, "cluster_edit", "clusters/" + id, payload.model_fields_set)
        db.flush()
        return detail_view(db, c)


@router.post("/clusters", status_code=422)
def no_manual_create(user=Depends(current_user)):
    raise Problem(422, "discovery_required", "请使用发现集群并勾选导入")
