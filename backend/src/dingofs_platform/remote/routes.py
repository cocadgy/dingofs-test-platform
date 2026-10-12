"""Authenticated HTTP metadata and same-origin, single-attach WebSocket streams."""

import asyncio
import anyio
from datetime import timedelta
import json
import secrets
import time
from urllib.parse import urlsplit, quote
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, text, update
from dingofs_platform.auth.dependencies import current_user
from dingofs_platform.auth.service import digest
from dingofs_platform.auth.users import actor_in_transaction
from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.service import lock_inventory
from .access import now, login, cluster, targets, log_target, terminal_target, valid
from .manager import ACTIVE, STREAM
from .models import RemoteSession
from .schemas import RemoteInput, RemoteAuth, RemoteView

router = APIRouter(prefix="/api/v1", tags=["remote-access"])


def owned(db, request, sid):
    actor, session = login(db, request.cookies.get("session", ""))
    row = db.get(RemoteSession, sid)
    if not row or row.actor_id != actor.id or row.login_session_id != session.id:
        raise Problem(404, "not_found", "远程会话不存在或不属于当前登录")
    return row


def view(db, request, row):
    manager = request.app.state.remote_manager
    m = db.get(Machine, row.machine_id)
    with manager.lock:
        slot = manager.slots.get(row.id)
        result = row.result
        if row.kind in ("read", "search"):
            result = slot.result if slot else None
        challenge = slot.challenge if slot and row.state == "needs_password" else None
    return dict(
        id=row.id,
        kind=row.kind,
        state=row.state,
        machine_id=m.id,
        machine_name=m.name,
        address=m.address,
        ssh_port=m.ssh_port,
        ssh_user=m.ssh_user,
        target_user=row.target_user,
        cluster_id=row.cluster_id,
        service_id=row.service_id,
        log_dir=row.log_root,
        expires_at=row.expires_at,
        challenge=challenge,
        auth_account=row.auth_account,
        error_code=row.error_code,
        message="结果缓存已释放，请重新读取或下载"
        if row.error_code == "result_evicted"
        else None,
        result=result,
    )


def quota(db, actor, mid, kind, settings):
    db.execute(text("SELECT pg_advisory_xact_lock(7412083)"))
    q = (
        select(func.count())
        .select_from(RemoteSession)
        .where(RemoteSession.state.in_(ACTIVE), RemoteSession.expires_at > now())
    )
    if (
        db.scalar(q.where(RemoteSession.machine_id == mid))
        >= settings.remote_machine_limit
    ):
        raise Problem(429, "remote_limit", "此机器的远程连接已达上限")
    limit = (
        settings.remote_terminal_limit
        if kind == "terminal"
        else settings.remote_follow_limit
    )
    if (
        db.scalar(
            q.where(RemoteSession.actor_id == actor.id, RemoteSession.kind == kind)
        )
        >= limit
    ):
        raise Problem(429, "remote_limit", "当前用户的此类会话已达上限")


@router.get("/clusters/{id}/remote-targets")
def remote_targets(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        return targets(db, cluster(db, id), user)


@router.post("/remote-sessions", status_code=202, response_model=RemoteView)
def create(request: Request, payload: RemoteInput, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        lock_inventory(db)
        actor, session = login(db, request.cookies.get("session", ""))
        c = cluster(db, payload.cluster_id)
        root = None
        parameters = {}
        if payload.kind == "terminal":
            if not payload.confirmed:
                raise Problem(
                    422, "confirmation_required", "必须确认连接目标和远程操作权限"
                )
            if payload.service_id or payload.file_id or payload.cursor:
                raise Problem(422, "invalid_request", "终端不接受日志文件参数")
            m = terminal_target(db, c, actor, payload.machine_id)
            target_user = m.ssh_user
            parameters = {"cols": payload.cols, "rows": payload.rows}
        else:
            if payload.machine_id:
                raise Problem(422, "invalid_request", "日志连接目标由服务主机决定")
            m, root, target_user = log_target(db, c, actor, payload.service_id)
            parameters = {"lines": payload.lines}
            if payload.kind == "search":
                if payload.file_id or payload.cursor:
                    raise Problem(422, "invalid_request", "目录搜索不接受文件参数")
                parameters.update(keyword=payload.keyword, case_sensitive=payload.case_sensitive)
            elif payload.kind != "files":
                try:
                    listing_id, index = (payload.file_id or "").split(":")
                    index = int(index)
                    listing = owned(db, request, listing_id)
                    if (
                        index < 0
                        or listing.kind != "files"
                        or listing.state != "succeeded"
                        or listing.cluster_id != c.id
                        or listing.service_id != payload.service_id
                        or listing.machine_id != m.id
                        or not valid(db, listing)
                    ):
                        raise ValueError()
                    entry = listing.result["files"][index]
                    if entry["file_id"] != payload.file_id:
                        raise ValueError()
                    parameters["name"] = entry["name"]
                except (ValueError, IndexError, KeyError, TypeError, Problem):
                    raise Problem(
                        422, "file_selection_stale", "请选择当前目录列表中的日志文件"
                    ) from None
                if payload.cursor:
                    parameters["cursor"] = payload.cursor.model_dump()
            elif payload.file_id or payload.cursor:
                raise Problem(422, "invalid_request", "目录列表不接受文件参数")
        quota(db, actor, m.id, payload.kind, request.app.state.settings)
        row = RemoteSession(
            actor_id=actor.id,
            login_session_id=session.id,
            kind=payload.kind,
            cluster_id=c.id,
            machine_id=m.id,
            cluster_revision=c.revision,
            machine_revision=m.revision,
            target_user=target_user,
            service_id=payload.service_id,
            log_root=root,
            parameters=parameters,
            state="pending",
            expires_at=now()
            + timedelta(
                seconds=request.app.state.settings.remote_lifetime_seconds
                if payload.kind in STREAM
                else 900
            ),
        )
        db.add(row)
        db.flush()
        db.add(
            AuditEvent(
                actor=actor.id,
                request_id=request.state.request_id,
                action="remote.create",
                entity="remote_sessions/" + row.id,
                detail={
                    "kind": row.kind,
                    "cluster_id": c.id,
                    "machine_id": m.id,
                    "service_id": row.service_id,
                    "target_user": target_user,
                    "file_id": payload.file_id,
                },
            )
        )
        result = view(db, request, row)
    request.app.state.remote_manager.launch(row.id)
    return result


@router.get("/remote-sessions/{id}", response_model=RemoteView)
def get(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db:
        owned(db, request, id)
    manager = request.app.state.remote_manager
    okay = manager.ensure_valid(id)
    with get_db(request) as db:
        row = owned(db, request, id)
        result = view(db, request, row)
        if row.state in {"closed", "failed", "interrupted"}:
            result.update(result=None, challenge=None)
        if not okay and row.state not in {"closed", "failed", "interrupted"}:
            result.update(
                state="closed",
                result=None,
                challenge=None,
                error_code="authorization_expired",
            )
        return result


@router.delete("/remote-sessions/{id}", status_code=204)
def close(id: str, request: Request, user=Depends(current_user)):
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        if actor.role == "admin":
            if not db.get(RemoteSession, id):
                raise Problem(404, "not_found", "远程会话不存在")
        else:
            owned(db, request, id)
        db.add(
            AuditEvent(
                actor=actor.id,
                request_id=request.state.request_id,
                action="remote.disconnect_requested",
                entity="remote_sessions/" + id,
                detail={},
            )
        )
    request.app.state.remote_manager.close(id)


@router.post(
    "/remote-sessions/{id}/authenticate", status_code=202, response_model=RemoteView
)
def authenticate(
    id: str, request: Request, payload: RemoteAuth, user=Depends(current_user)
):
    manager = request.app.state.remote_manager
    with get_db(request) as db, db.begin():
        actor_in_transaction(db, request)
        lock_inventory(db)
        row = owned(db, request, id)
        if (
            row.state != "needs_password"
            or not valid(db, row)
            or not row.auth_expires_at
            or row.auth_expires_at <= now()
            or row.auth_attempts >= 3
            or not secrets.compare_digest(
                row.challenge_hash or "", digest(payload.challenge)
            )
        ):
            raise Problem(409, "auth_stale", "密码请求已失效，请重新连接")
        row.auth_attempts += 1
        row.challenge_hash = None
        row.state = "pending"
        account = row.auth_account
        result = view(db, request, row)
    manager.launch(id, password=payload.password, auth_account=account)
    return result


class DownloadResponse(StreamingResponse):
    def __init__(self, *args, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A disconnect can happen before the body iterator ever starts.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self.release)


@router.get("/remote-sessions/{id}/download")
def download(id: str, request: Request, user=Depends(current_user)):
    manager = request.app.state.remote_manager
    with get_db(request) as db:
        row = owned(db, request, id)
        if row.error_code == "result_evicted":
            raise Problem(410, "result_evicted", "结果缓存已释放，请重新下载")
        if row.kind != "download" or row.state != "succeeded" or not valid(db, row):
            raise Problem(409, "download_unavailable", "下载尚未完成或已过期")
        name = row.parameters["name"]
    with manager.lock:
        slot = manager.slots.get(id)
        if not slot or not slot.tempdir:
            raise Problem(410, "download_expired", "下载内容已过期，请重新下载")
        source = open(slot.tempdir.name + "/content", "rb")
        slot.download_readers += 1
        size = slot.download_size

    def release():
        manager.release_download(slot, source)

    def chunks():
        checked = 0
        try:
            while True:
                if time.monotonic() - checked >= 2:
                    if not manager.ensure_valid(id):
                        return
                    checked = time.monotonic()
                data = source.read(65536)
                if not data:
                    return
                yield data
        finally:
            release()

    return DownloadResponse(
        chunks(),
        release=release,
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(name, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def same_origin(ws):
    origin = ws.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
        scheme = "https" if ws.url.scheme == "wss" else "http"
        return (
            parsed.scheme == scheme
            and parsed.netloc == ws.headers.get("host")
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
        )
    except ValueError:
        return False


@router.websocket("/remote-sessions/{id}/stream")
async def stream(ws: WebSocket, id: str):
    manager = ws.app.state.remote_manager

    def authorize():
        with ws.app.state.session_factory() as db:
            row = owned(db, ws, id)
            if (
                row.kind not in STREAM
                or row.state not in {"ready", "running"}
                or not valid(db, row)
            ):
                raise Problem(403, "stream_unavailable", "会话不可连接")
            return row.kind

    if not same_origin(ws):
        await ws.close(code=1008)
        return
    try:
        kind = await asyncio.to_thread(authorize)
    except Problem:
        await ws.close(code=1008)
        return
    if not manager.attach(id):
        await ws.close(code=1008)
        return

    def mark_running():
        with ws.app.state.session_factory.begin() as db:
            db.execute(
                update(RemoteSession)
                .where(RemoteSession.id == id, RemoteSession.state == "ready")
                .values(state="running")
            )

    try:
        await ws.accept()
        await asyncio.to_thread(mark_running)
        heartbeat = time.monotonic()
        checked = 0
        while True:
            if time.monotonic() - checked >= 2:

                def authorized_target():
                    with ws.app.state.session_factory() as db:
                        row = owned(db, ws, id)
                        return valid(db, row)

                if not await asyncio.to_thread(authorized_target):
                    await ws.send_json(
                        {"type": "closed", "reason": "authorization_expired"}
                    )
                    break
                checked = time.monotonic()
            for _ in range(16):
                event = manager.pop(id)
                if not event:
                    break
                await asyncio.wait_for(ws.send_json(event), timeout=5)
                if event["type"] in {"closed", "error"}:
                    return
            if time.monotonic() - heartbeat >= 10:
                await ws.send_json({"type": "heartbeat"})
                heartbeat = time.monotonic()
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
            except TimeoutError:
                continue
            if len(raw.encode("utf-8")) > 16384:
                await ws.close(code=1009)
                break
            try:
                event = json.loads(raw)
            except ValueError:
                await ws.close(code=1008)
                break
            if not isinstance(event, dict):
                await ws.close(code=1008)
                break
            et = event.get("type")
            if et == "heartbeat":
                continue
            if et in {"pause", "close"}:
                break
            if kind != "terminal":
                await ws.close(code=1008)
                break
            if (
                et == "input"
                and isinstance(event.get("data"), str)
                and len(event["data"].encode("utf-8")) <= 8192
            ):
                await asyncio.to_thread(
                    manager.send, id, {"type": "input", "data": event["data"]}
                )
            elif et == "resize" and all(
                type(event.get(k)) is int and 1 <= event[k] <= 500
                for k in ("cols", "rows")
            ):
                await asyncio.to_thread(
                    manager.send,
                    id,
                    {"type": "resize", "cols": event["cols"], "rows": event["rows"]},
                )
            else:
                await ws.close(code=1008)
                break
    except (WebSocketDisconnect, TimeoutError, RuntimeError, Problem):
        pass
    finally:
        # Starlette can cancel the task immediately after accept/disconnect.
        # Cleanup must survive that cancellation, including the initial state update.
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(manager.close, id, "stream_disconnected")
            try:
                await asyncio.wait_for(ws.close(), timeout=2)
            except (RuntimeError, TimeoutError, WebSocketDisconnect):
                pass
