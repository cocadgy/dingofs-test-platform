from fastapi import APIRouter, Depends, Request, Query, BackgroundTasks
from pydantic import ValidationError
from sqlalchemy import select, func
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from .permissions import require_manage
from .credentials import credential_changes
from .host_identity import sync_host_identifiers
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
    except ValidationError as exc:
        if kind == "machines":
            labels = {
                "name": "名称（支持中文，1–120 个字符）",
                "address": "主机地址（IP 或主机名）",
                "aliases": "主机别名（填写服务 Host，不是中文展示名称）",
                "ssh_user": "SSH 用户（英文字母、数字、下划线、点或横线）",
                "ssh_port": "SSH 端口（1–65535）",
                "ssh_password": "SSH 密码",
                "clear_ssh_password": "清除 SSH 密码选项",
                "credential_ref": "凭据引用",
                "physical_id": "物理机标识",
                "tags": "标签",
                "maintenance": "维护状态",
            }
            # Return field labels only: never echo passwords or validation inputs.
            fields = list(
                dict.fromkeys(
                    error["loc"][0]
                    if error["loc"] and error["loc"][0] in labels
                    else "unknown_field"
                    for error in exc.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                )
            )
            raise Problem(
                422,
                "invalid_fields",
                "请检查以下字段："
                + "、".join(labels.get(field, "不支持的字段") for field in fields),
                {"fields": fields},
            ) from None
        raise Problem(422, "invalid_fields", "字段格式错误或包含不支持的字段") from None


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
def create(kind: str, request: Request, payload: dict, background_tasks: BackgroundTasks, user=Depends(current_user)):
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
        if kind == "machines":
            sync_host_identifiers(db, row)
        set_links(db, kind, row, ids)
        audit(db, user, "create", kind + "/" + row.id, payload)
        if kind == "machines" and not row.ssh_password_ciphertext:
            row.collection_status = "failed"
            row.collection_error = "请先为该机器配置 SSH 密码，再更新机器信息"
        view = serialize(db, kind, row)
    if kind == "machines" and view["has_ssh_password"]:
        from .collection import begin_collection
        from .hardware_routes import collect_created_machine

        # Commit the resource before reserving a bounded background collection.
        try:
            token, config = begin_collection(request, view["id"], view["revision"])
        except Problem:
            # Concurrent edits/session revocation must not roll back registration.
            with get_db(request) as db:
                return serialize(db, kind, db.get(model, view["id"]))
        background_tasks.add_task(
            collect_created_machine, request, view["id"], view["revision"], token, config
        )
        with get_db(request) as db:
            view = serialize(db, kind, db.get(model, view["id"]))
    return view


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
        if kind == "machines":
            sync_host_identifiers(db, row)
        set_links(db, kind, row, ids)
        audit(db, user, "update", kind + "/" + id, payload)
        db.flush()
        return serialize(db, kind, row)
