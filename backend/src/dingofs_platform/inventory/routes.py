from fastapi import APIRouter, Depends, Request, Query
from pydantic import ValidationError
from sqlalchemy import select, func
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from .permissions import require_manage
from .credentials import credential_changes
from .schemas import MachineInput, ClusterInput, EnvironmentInput
from .service import (
    MODELS,
    serialize,
    lock_inventory,
    validate_refs,
    set_links,
    audit,
    check_archive,
)

router = APIRouter(prefix="/api/v1")
SCHEMAS = {
    "machines": MachineInput,
    "clusters": ClusterInput,
    "environments": EnvironmentInput,
}


def model_for(kind):
    if kind not in MODELS:
        raise Problem(404, "not_found", "资源类型不存在")
    return MODELS[kind]


def validated(kind, data):
    try:
        return SCHEMAS[kind].model_validate(data).model_dump()
    except ValidationError:
        raise Problem(422, "invalid_fields", "字段格式错误或包含不支持的字段")


@router.get("/{kind}")
def listing(
    kind: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", max_length=120),
    user=Depends(current_user),
):
    model = model_for(kind)
    with get_db(request) as db:
        query = select(model).where(model.name.icontains(q, autoescape=True))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        return {
            "total": total,
            "items": [
                serialize(db, kind, r)
                for r in db.scalars(
                    query.order_by(model.created_at, model.id)
                    .offset(offset)
                    .limit(limit)
                )
            ],
        }


@router.get("/{kind}/{id}")
def detail(kind: str, id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        row = db.get(model_for(kind), id)
        if not row:
            raise Problem(404, "not_found", "资源不存在")
        return serialize(db, kind, row)


@router.post("/{kind}", status_code=201)
def create(kind: str, request: Request, payload: dict, user=Depends(current_user)):
    model = model_for(kind)
    if kind != "machines" and user.role != "admin":
        raise Problem(403, "forbidden", "需要管理员权限")
    data = validated(kind, payload)
    if kind == "machines":
        data = credential_changes(
            data, request.app.state.settings.credential_encryption_key
        )
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        validate_refs(db, kind, data)
        ids = data.pop("machine_ids", [])
        row = model(**data)
        if kind == "machines":
            row.creator_id = user.id
        db.add(row)
        db.flush()
        set_links(db, kind, row, ids)
        audit(db, user, "create", kind + "/" + row.id, payload)
        return serialize(db, kind, row)


@router.patch("/{kind}/{id}")
def patch(
    kind: str, id: str, request: Request, payload: dict, user=Depends(current_user)
):
    model = model_for(kind)
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        row = db.scalar(select(model).where(model.id == id).with_for_update())
        if not row:
            raise Problem(404, "not_found", "资源不存在")
        require_manage(user, row)
        revision = payload.get("base_revision")
        if type(revision) != int:
            raise Problem(422, "invalid_revision", "需要整数 base_revision")
        if revision != row.revision:
            raise Problem(
                409, "revision_conflict", "资源已被更新，请重新加载后合并修改"
            )
        changes = {
            k: v for k, v in payload.items() if k not in ("base_revision", "archived")
        }
        current = serialize(db, kind, row)
        data = validated(
            kind,
            {
                **{k: current[k] for k in SCHEMAS[kind].model_fields if k in current},
                **changes,
            },
        )
        if kind == "machines":
            data = credential_changes(
                data, request.app.state.settings.credential_encryption_key
            )
        archived = payload.get("archived", row.archived)
        if type(archived) != bool:
            raise Problem(422, "invalid_fields", "archived 必须为布尔值")
        if archived:
            check_archive(db, kind, id)
        else:
            validate_refs(db, kind, data)
        ids = data.pop("machine_ids", [])
        for k, v in data.items():
            setattr(row, k, v)
        row.archived = archived
        row.revision += 1
        set_links(db, kind, row, ids)
        audit(db, user, "update", kind + "/" + id, payload)
        db.flush()
        return serialize(db, kind, row)
