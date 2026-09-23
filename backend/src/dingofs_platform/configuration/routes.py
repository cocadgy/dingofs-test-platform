import hashlib, difflib
from typing import Literal
from fastapi import APIRouter, Depends, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Environment
from dingofs_platform.inventory.service import active, lock_inventory, audit
from dingofs_platform.inventory.permissions import require_manage
from .models import ConfigDraft, ConfigVersion
from .yaml_document import parse, merge

router = APIRouter(prefix="/api/v1/configs")


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=0, strict=True)


class DraftInput(Revision):
    mode: Literal["yaml", "form"]
    yaml_text: str | None = None
    field_updates: dict | None = None


class DraftResponse(BaseModel):
    revision: int
    yaml_text: str
    document_kind: Literal["platform-environment", "dingo-topology"]
    form_values: dict[str, str]
    validation: dict[str, bool]


def owner(db, kind, id):
    models = {"cluster": Cluster, "environment": Environment}
    if kind not in models:
        raise Problem(404, "not_found", "配置类型不存在")
    return active(db, models[kind], id)


def draft(db, kind, id):
    return db.scalar(
        select(ConfigDraft).where(
            ConfigDraft.owner_kind == kind, ConfigDraft.owner_id == id
        )
    )


def output(row, kind):
    text = row.yaml_text if row else "{}\n"
    _, values = parse(text)
    allowed = {"filesystem", "mount_root", "dingo_path", "vdbench_path"}
    return {
        "document_kind": "platform-environment"
        if kind == "environment"
        else "dingo-topology",
        "form_values": {
            k: v for k, v in values.items() if k in allowed and isinstance(v, str)
        }
        if kind == "environment"
        else {},
        "revision": row.revision if row else 0,
        "yaml_text": row.yaml_text if row else "{}\n",
        "validation": {"syntax_valid": bool(row), "tool_validated": False},
    }


@router.get("/{kind}/{id}/draft", response_model=DraftResponse)
def get_draft(kind: str, id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        owner(db, kind, id)
        return output(draft(db, kind, id), kind)


@router.put("/{kind}/{id}/draft", response_model=DraftResponse)
def save(
    kind: str,
    id: str,
    payload: DraftInput,
    request: Request,
    user=Depends(current_user),
):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        require_manage(user, owner(db, kind, id))
        row = draft(db, kind, id)
        if payload.base_revision != (row.revision if row else 0):
            raise Problem(
                409, "revision_conflict", "草稿已更新，保留当前输入，请重新加载后合并"
            )
        if payload.mode == "form":
            if kind != "environment" or payload.yaml_text is not None:
                raise Problem(422, "invalid_fields", "该配置仅支持 YAML 编辑")
            text = merge(row.yaml_text if row else "", payload.field_updates or {})
        else:
            if payload.yaml_text is None or payload.field_updates is not None:
                raise Problem(422, "invalid_fields", "需要 yaml_text")
            text = payload.yaml_text
            parse(text)
        if row:
            row.yaml_text = text
            row.revision += 1
        else:
            row = ConfigDraft(owner_kind=kind, owner_id=id, yaml_text=text)
            db.add(row)
        audit(db, user, "save_draft", kind + "/" + id, [])
        db.flush()
        return output(row, kind)


@router.post("/{kind}/{id}/publish", status_code=201)
def publish(
    kind: str, id: str, payload: Revision, request: Request, user=Depends(current_user)
):
    with get_db(request) as db, db.begin():
        lock_inventory(db)
        require_manage(user, owner(db, kind, id))
        row = draft(db, kind, id)
        if not row or row.revision != payload.base_revision:
            raise Problem(409, "revision_conflict", "草稿不存在或已更新")
        parse(row.yaml_text)
        n = (
            db.scalar(
                select(func.max(ConfigVersion.version)).where(
                    ConfigVersion.owner_kind == kind, ConfigVersion.owner_id == id
                )
            )
            or 0
        ) + 1
        v = ConfigVersion(
            owner_kind=kind,
            owner_id=id,
            version=n,
            yaml_text=row.yaml_text,
            sha256=hashlib.sha256(row.yaml_text.encode()).hexdigest(),
            author=user.id,
        )
        db.add(v)
        audit(db, user, "publish", kind + "/" + id, [])
        db.flush()
        return {"version": n, "sha256": v.sha256, "deployed": False}


@router.get("/{kind}/{id}/versions")
def versions(kind: str, id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        owner(db, kind, id)
        rows = db.scalars(
            select(ConfigVersion)
            .where(ConfigVersion.owner_kind == kind, ConfigVersion.owner_id == id)
            .order_by(ConfigVersion.version.desc())
            .limit(100)
        )
        return {
            "items": [
                {
                    "version": r.version,
                    "yaml_text": r.yaml_text,
                    "sha256": r.sha256,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        }


@router.get("/{kind}/{id}/diff")
def diff(
    kind: str,
    id: str,
    request: Request,
    from_version: int = Query(alias="from", ge=1),
    to_version: int = Query(alias="to", ge=1),
    user=Depends(current_user),
):
    with get_db(request) as db:
        owner(db, kind, id)
        texts = []
        for n in (from_version, to_version):
            row = db.scalar(
                select(ConfigVersion).where(
                    ConfigVersion.owner_kind == kind,
                    ConfigVersion.owner_id == id,
                    ConfigVersion.version == n,
                )
            )
            if not row:
                raise Problem(404, "not_found", "配置版本不存在")
            texts.append(row.yaml_text.splitlines(keepends=True))
        return {
            "diff": "".join(
                difflib.unified_diff(
                    *texts, fromfile=str(from_version), tofile=str(to_version)
                )
            )
        }
