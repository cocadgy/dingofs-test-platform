"""Server-issued host key challenges, scoped to one machine revision and endpoint."""

import base64
import hashlib
import re
from .permissions import require_manage
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import paramiko
from dingofs_platform.errors import Problem


def key_info(key):
    return {
        "key_type": key.get_name(),
        "key_base64": key.get_base64(),
        "fingerprint": "SHA256:"
        + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("="),
    }


def decode_key(info):
    kind = info["key_type"]
    encoded = info["key_base64"]
    if (
        not isinstance(kind, str)
        or len(kind) > 80
        or not isinstance(encoded, str)
        or len(encoded) > 16384
    ):
        raise ValueError("invalid host key")
    key = paramiko.PKey.from_type_string(kind, base64.b64decode(encoded, validate=True))
    if key.get_name() != kind:
        raise ValueError("host key type mismatch")
    return key


def scoped_trust(row):
    pin = row.ssh_host_key
    if pin and pin["host"] == row.address and pin["port"] == row.ssh_port:
        return pin
    return None


def make_challenge(row, info):
    normalized = key_info(decode_key(info))
    pin = scoped_trust(row)
    previous = pin["fingerprint"] if pin else info.get("previous_fingerprint")
    if previous and not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", previous):
        previous = None
    return {
        **normalized,
        "previous_fingerprint": previous,
        "host": row.address,
        "port": row.ssh_port,
        "challenge_id": str(uuid4()),
        "revision": row.revision,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }


def public_trust(row):
    trusted = scoped_trust(row)
    pending = row.ssh_trust_pending
    if pending and (
        pending["revision"] != row.revision
        or pending["host"] != row.address
        or pending["port"] != row.ssh_port
    ):
        pending = None
    fields = ("key_type", "fingerprint", "host", "port", "trusted_at")
    view = {
        "trusted": {k: trusted[k] for k in fields if k in trusted} if trusted else None,
        "pending": None,
    }
    if pending:
        view["pending"] = {
            k: pending[k]
            for k in (
                "challenge_id",
                "key_type",
                "fingerprint",
                "previous_fingerprint",
                "host",
                "port",
                "expires_at",
            )
        }
    return view


def trust_key(request, id, revision, challenge_id):
    from dingofs_platform.db import get_db
    from dingofs_platform.auth.users import actor_in_transaction
    from dingofs_platform.audit.models import AuditEvent
    from .collection import locked_machine
    from .service import serialize

    with get_db(request) as db, db.begin():
        actor = actor_in_transaction(db, request)
        row = locked_machine(db, id)
        require_manage(actor, row)
        pending = row.ssh_trust_pending
        now = datetime.now(timezone.utc)
        if (
            row.archived
            or row.revision != revision
            or not pending
            or pending["revision"] != revision
            or pending["challenge_id"] != challenge_id
            or pending["host"] != row.address
            or pending["port"] != row.ssh_port
            or datetime.fromisoformat(pending["expires_at"]) <= now
        ):
            raise Problem(
                409,
                "trust_challenge_stale",
                "指纹确认已过期或机器配置已变化，请重新更新机器信息",
            )
        if (
            row.collection_token
            and row.collection_expires_at
            and row.collection_expires_at > now
        ):
            raise Problem(409, "collection_busy", "机器正在采集，请稍后重新确认")
        key = key_info(decode_key(pending))
        row.ssh_host_key = {
            **key,
            "host": row.address,
            "port": row.ssh_port,
            "trusted_at": now.isoformat(),
        }
        row.ssh_trust_pending = None
        row.collection_status = "never"
        row.collection_error = None
        row.revision += 1
        db.add(
            AuditEvent(
                actor=actor.id,
                request_id=db.info.get("request_id", ""),
                action="trust_host_key",
                entity="machines/" + id,
                detail={
                    "host": row.address,
                    "port": row.ssh_port,
                    "fingerprint": key["fingerprint"],
                    "previous_fingerprint": pending.get("previous_fingerprint"),
                },
            )
        )
        db.flush()
        return serialize(db, "machines", row)
