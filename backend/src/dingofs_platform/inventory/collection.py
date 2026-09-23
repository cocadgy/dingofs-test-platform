"""Short transactions around a bounded probe; no DB locks during SSH."""

from .permissions import require_manage
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select
from dingofs_platform.db import get_db
from dingofs_platform.errors import Problem
from dingofs_platform.auth.users import actor_in_transaction
from .models import Machine
from .credentials import decrypt_password
from .ssh_transport import SSHConfig
from .service import serialize, audit
from .host_trust import scoped_trust, make_challenge


def locked_machine(db, id):
    row = db.scalar(select(Machine).where(Machine.id == id).with_for_update())
    if not row:
        raise Problem(404, "not_found", "机器不存在")
    return row


def begin_collection(request, id, revision):
    settings = request.app.state.settings
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        row = locked_machine(db, id)
        require_manage(actor, row)
        now = datetime.now(timezone.utc)
        if row.archived:
            raise Problem(409, "machine_archived", "已归档机器不能采集")
        if row.revision != revision:
            raise Problem(409, "revision_conflict", "机器配置已更新，请刷新后重试")
        if (
            row.collection_token
            and row.collection_expires_at
            and row.collection_expires_at > now
        ):
            raise Problem(409, "collection_busy", "该机器正在采集，请稍后刷新查看")
        if not row.ssh_password_ciphertext:
            raise Problem(422, "ssh_password_missing", "请先为该机器配置 SSH 密码")
        config = SSHConfig(
            row.address,
            row.ssh_port,
            row.ssh_user,
            decrypt_password(
                row.ssh_password_ciphertext, settings.credential_encryption_key
            ),
            settings.ssh_known_hosts,
            trusted_host_key=scoped_trust(row),
        )
        token = str(uuid4())
        row.collection_token = token
        row.collection_expires_at = now + timedelta(
            seconds=settings.collection_timeout_seconds + 5
        )
        row.last_attempt_at = now
        row.last_attempt_info = None
        row.ssh_trust_pending = None
        row.collection_status = "collecting"
        row.collection_error = None
        audit(db, actor, "collect_start", "machines/" + id, [])
        return token, config


def abandon(request, id, token):
    # Internal cleanup only; never changes a successful snapshot or a newer job.
    with get_db(request) as db, db.begin():
        row = locked_machine(db, id)
        if row.collection_token == token:
            row.collection_token = None
            row.collection_expires_at = None
            row.collection_status = "interrupted"
            row.collection_error = "采集未提交，请刷新后重试"


def finish_collection(request, id, token, revision, result):
    error = None
    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        row = locked_machine(db, id)
        require_manage(actor, row)
        if row.collection_token != token:
            raise Problem(409, "collection_replaced", "本次采集已被后续采集替代")
        if (
            row.revision != revision
            or row.archived
            or row.collection_expires_at <= datetime.now(timezone.utc)
        ):
            row.collection_status = "interrupted"
            row.collection_error = "机器配置已变化或采集已过期，请重新更新"
            error = Problem(409, "collection_stale", row.collection_error)
        else:
            row.collection_status = result["status"]
            row.collection_error = result.get("error")
            row.last_attempt_info = result.get("hardware_info")
            if result["status"] == "success":
                row.hardware_info = result["hardware_info"]
                row.last_success_at = datetime.now(timezone.utc)
            row.revision += 1
            if result["status"] == "needs_trust":
                row.ssh_trust_pending = make_challenge(row, result["host_key"])
            audit(db, actor, "collect_" + result["status"], "machines/" + id, [])
        row.collection_token = None
        row.collection_expires_at = None
        db.flush()
        view = serialize(db, "machines", row)
    if error:
        raise error
    return view
