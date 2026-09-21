import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from dingofs_platform.auth.models import Session
from dingofs_platform.auth.service import verify_login, digest, csrf_token
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


def identity(user, token):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "csrf_token": csrf_token(token),
    }


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise Problem(403, "origin_failed", "请求来源不匹配")
    with get_db(request) as db:
        user = verify_login(db, body.username, body.password)
        token = secrets.token_urlsafe(48)
        # Rotate an existing session if the browser logs in again.
        db.execute(
            delete(Session).where(
                Session.token_hash == digest(request.cookies.get("session", ""))
            )
        )
        db.add(
            Session(
                token_hash=digest(token),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(hours=request.app.state.settings.session_hours),
            )
        )
        db.commit()
        response.set_cookie(
            "session",
            token,
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="strict",
            max_age=request.app.state.settings.session_hours * 3600,
            path="/",
        )
        return identity(user, token)


@router.get("/me")
def me(request: Request):
    return identity(current_user(request), request.cookies["session"])


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    current_user(request)
    with get_db(request) as db:
        db.execute(
            delete(Session).where(
                Session.token_hash == digest(request.cookies["session"])
            )
        )
        db.commit()
    response.delete_cookie("session", path="/")
