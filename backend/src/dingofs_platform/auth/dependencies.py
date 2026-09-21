import secrets
from datetime import datetime, timezone
from fastapi import Request
from sqlalchemy import select
from dingofs_platform.auth.models import Session, User
from dingofs_platform.auth.service import digest, csrf_token
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem


def current_user(request: Request):
    token = request.cookies.get("session", "")
    with get_db(request) as db:
        session = db.scalar(select(Session).where(Session.token_hash == digest(token)))
        if not session or session.expires_at <= datetime.now(timezone.utc):
            raise Problem(401, "unauthenticated", "请先登录")
        user = db.get(User, session.user_id)
        if not user or user.disabled:
            raise Problem(401, "unauthenticated", "请重新登录")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), csrf_token(token)
            ):
                raise Problem(403, "csrf_failed", "请求验证失败，请刷新页面")
        db.expunge(user)
        return user


def require_admin(request: Request):
    user = current_user(request)
    if user.role != "admin":
        raise Problem(403, "forbidden", "该操作需要管理员权限")
    return user
