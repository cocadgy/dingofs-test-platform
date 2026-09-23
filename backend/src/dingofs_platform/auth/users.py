"""User administration and password-verified profile updates."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response, Query
from sqlalchemy import select, delete, func, text
from .models import User, Session
from .schemas import (
    NewUser,
    UserStatus,
    UserRevision,
    ProfileUpdate,
    UserView,
    UserList,
)
from .service import hasher, password_matches, digest
from .dependencies import current_user, require_admin
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.service import audit

router = APIRouter(prefix="/api/v1", tags=["users"])
RESET_PASSWORD = "123456"


def lock_accounts(db):
    db.execute(text("SELECT pg_advisory_xact_lock(7412082)"))


def actor_in_transaction(db, request, admin=False):
    # Recheck after obtaining the account lock: another request may have
    # revoked this session between the dependency check and this transaction.
    lock_accounts(db)
    session = db.scalar(
        select(Session).where(
            Session.token_hash == digest(request.cookies.get("session", ""))
        )
    )
    actor = db.get(User, session.user_id) if session else None
    if not actor or actor.disabled or session.expires_at <= datetime.now(timezone.utc):
        raise Problem(401, "unauthenticated", "请重新登录")
    if admin and actor.role != "admin":
        raise Problem(403, "forbidden", "该操作需要管理员权限")
    return actor


def target(db, id, revision):
    user = db.get(User, id)
    if not user:
        raise Problem(404, "not_found", "用户不存在")
    if user.revision != revision:
        raise Problem(409, "revision_conflict", "用户信息已更新，请刷新用户列表")
    return user


def protect_last_admin(db, user):
    if user.role == "admin" and not user.disabled:
        count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.disabled == False)
        )
        if count <= 1:
            raise Problem(409, "last_admin", "不能禁用或删除最后一个启用的管理员")


def revoke(db, id):
    db.execute(delete(Session).where(Session.user_id == id))


@router.get("/users", response_model=UserList)
def list_users(
    request: Request,
    q: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(require_admin),
):
    with get_db(request) as db:
        query = select(User).where(User.username.icontains(q, autoescape=True))
        return {
            "items": [
                UserView.model_validate(u)
                for u in db.scalars(
                    query.order_by(User.created_at, User.id).limit(limit).offset(offset)
                )
            ],
            "total": db.scalar(select(func.count()).select_from(query.subquery())),
        }


@router.post("/users", status_code=201, response_model=UserView)
def add_user(request: Request, payload: NewUser, user=Depends(require_admin)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request, admin=True)
        if db.scalar(select(User.id).where(User.username == payload.username)):
            raise Problem(409, "username_exists", "用户名已存在")
        added = User(
            username=payload.username,
            email=payload.email,
            password_hash=hasher.hash(payload.password),
            role=payload.role,
        )
        db.add(added)
        db.flush()
        audit(
            db, actor, "user.create", "users/" + added.id, ["username", "email", "role"]
        )
        return UserView.model_validate(added)


@router.patch("/users/{id}", response_model=UserView)
def set_status(
    id: str, request: Request, payload: UserStatus, user=Depends(require_admin)
):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request, admin=True)
        row = target(db, id, payload.base_revision)
        if payload.disabled:
            protect_last_admin(db, row)
            revoke(db, row.id)
        row.disabled = payload.disabled
        row.revision += 1
        audit(
            db,
            actor,
            "user.disable" if row.disabled else "user.enable",
            "users/" + id,
            ["disabled"],
        )
        db.flush()
        return UserView.model_validate(row)


@router.post("/users/{id}/reset-password")
def reset_password(
    id: str, request: Request, payload: UserRevision, user=Depends(require_admin)
):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request, admin=True)
        row = target(db, id, payload.base_revision)
        row.password_hash = hasher.hash(RESET_PASSWORD)
        row.revision += 1
        revoke(db, id)
        audit(db, actor, "user.reset_password", "users/" + id, ["password"])
        db.flush()
        return {"revision": row.revision, "reauthenticate": actor.id == id}


@router.delete("/users/{id}", status_code=204)
def delete_user(
    id: str,
    request: Request,
    base_revision: int = Query(ge=1),
    user=Depends(require_admin),
):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request, admin=True)
        row = target(db, id, base_revision)
        protect_last_admin(db, row)
        revoke(db, id)
        audit(db, actor, "user.delete", "users/" + id, [])
        db.delete(row)


@router.patch("/auth/profile")
def profile(
    request: Request,
    response: Response,
    payload: ProfileUpdate,
    user=Depends(current_user),
):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        if not password_matches(actor.password_hash, payload.current_password):
            raise Problem(403, "password_incorrect", "当前密码不正确，修改未保存")
        fields = []
        if payload.email is not None:
            actor.email = payload.email
            fields.append("email")
        if payload.new_password is not None:
            actor.password_hash = hasher.hash(payload.new_password)
            revoke(db, actor.id)
            fields.append("password")
            response.delete_cookie("session", path="/")
        actor.revision += 1
        audit(db, actor, "user.profile_update", "users/" + actor.id, fields)
        db.flush()
        return {
            "email": actor.email,
            "revision": actor.revision,
            "reauthenticate": payload.new_password is not None,
        }
