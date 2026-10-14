"""Single-API-process supervisor. DB stores metadata; buffers have bounded lifetime."""

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from sqlalchemy import update
from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.auth.service import digest
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.host_trust import scoped_trust, make_challenge
from dingofs_platform.inventory.ssh_transport import SSHConfig
from .access import now, valid
from .models import RemoteSession

ACTIVE = {"pending", "connecting", "ready", "running", "needs_password"}
STREAM = {"terminal", "log-follow"}
MAX_BUFFER = 5 * 1024 * 1024
RESULT_TTL_SECONDS = 900
# Per API process, across users: retain at most 64 completed sessions and
# 256 MiB of serialized results, queued output, and download spools. Live
# workers, attached streams, and HTTP download readers retain ownership until
# they finish. Explicit expiration/revocation can still terminate any session.
MAX_RETAINED_SLOTS = 64
MAX_RETAINED_BYTES = 256 * 1024 * 1024


@dataclass
class Slot:
    job: object = None
    thread: object = None
    events: deque = field(default_factory=deque)
    queued: int = 0
    result: dict | None = None
    result_bytes: int = 0
    challenge: str | None = None
    attached: bool = False
    attach_deadline: float = field(default_factory=lambda: time.monotonic() + 30)
    last_input: float = field(default_factory=time.monotonic)
    tempdir: object = None
    download: object = None
    download_size: int = 0
    download_received: int = 0
    download_readers: int = 0
    expires: float = field(
        default_factory=lambda: time.monotonic() + RESULT_TTL_SECONDS
    )
    completed_at: float | None = None
    stopped: bool = False


class RemoteManager:
    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.slots = {}
        self.stop_event = threading.Event()
        self.sweeper = None

    def startup(self):
        with self.app.state.session_factory.begin() as db:
            db.execute(
                update(RemoteSession)
                .where(RemoteSession.state.in_(ACTIVE))
                .values(
                    state="interrupted", error_code="api_restarted", closed_at=now()
                )
            )
        self.sweeper = threading.Thread(target=self._sweep, daemon=True)
        self.sweeper.start()

    def shutdown(self):
        self.stop_event.set()
        with self.lock:
            ids = list(self.slots)
        for sid in ids:
            self.close(sid, "api_shutdown")
        if self.sweeper:
            self.sweeper.join(timeout=2)
        with self.lock:
            slots = list(self.slots.values())
        for slot in slots:
            if slot.thread and slot.thread is not threading.current_thread():
                slot.thread.join(timeout=3)
            self._cleanup(slot)

    @staticmethod
    def _release_result(slot):
        if slot.download:
            slot.download.close()
            slot.download = None
        if slot.tempdir:
            slot.tempdir.cleanup()
            slot.tempdir = None
        slot.result = None
        slot.result_bytes = 0
        slot.download_size = 0
        slot.download_received = 0

    @classmethod
    def _cleanup(cls, slot):
        cls._release_result(slot)
        slot.challenge = None
        slot.events.clear()
        slot.queued = 0

    @staticmethod
    def _complete_slot(slot):
        if slot.completed_at is None:
            slot.completed_at = time.monotonic()
            slot.expires = slot.completed_at + RESULT_TTL_SECONDS

    def _prune_completed(self):
        # Call with self.lock held. Never discard a worker or a socket's unread
        # final output just to make room for completed result caches. Pinned
        # output still counts toward the budget, so opening readers cannot grow
        # the retained cache without bound.
        completed = sorted(
            (
                (sid, slot)
                for sid, slot in self.slots.items()
                if slot.completed_at is not None and slot.job is None
            ),
            key=lambda item: item[1].completed_at,
        )
        retained_bytes = sum(
            slot.result_bytes + slot.download_received + slot.queued
            for _, slot in completed
        )
        retained_slots = len(completed)
        for sid, slot in completed:
            if (
                retained_slots <= MAX_RETAINED_SLOTS
                and retained_bytes <= MAX_RETAINED_BYTES
            ):
                break
            if slot.attached or slot.download_readers:
                continue
            with self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                if row:
                    if row.state == "succeeded":
                        self._finish_row(db, row, "closed", "result_evicted")
                    row.result = None
            retained_bytes -= slot.result_bytes + slot.download_received + slot.queued
            retained_slots -= 1
            self._cleanup(slot)
            self.slots.pop(sid, None)

    def release_download(self, slot, source):
        with self.lock:
            if source.closed:
                return
            source.close()
            slot.download_readers -= 1
            self._prune_completed()

    def launch(self, sid, password=None, auth_account=None):
        with self.lock:
            old = self.slots.get(sid)
            if old:
                self._cleanup(old)
            slot = Slot()
            self.slots[sid] = slot
            slot.thread = threading.Thread(
                target=self._run, args=(sid, slot, password, auth_account), daemon=True
            )
            slot.thread.start()

    def _run(self, sid, slot, password, auth_account):
        job = None
        try:
            with self.lock, self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                if slot.stopped or row.state not in ACTIVE or not valid(db, row):
                    return
                m = db.get(Machine, row.machine_id)
                if not m.ssh_password_ciphertext:
                    self._finish_row(db, row, "failed", "ssh_password_missing")
                    return
                config = SSHConfig(
                    m.address,
                    m.ssh_port,
                    m.ssh_user,
                    decrypt_password(
                        m.ssh_password_ciphertext,
                        self.app.state.settings.credential_encryption_key,
                    ),
                    self.app.state.settings.ssh_known_hosts,
                    scoped_trust(m),
                )
                kind = row.kind
                from .worker import RemoteRequest, RemoteJob

                req = RemoteRequest(
                    kind=kind,
                    target_user=row.target_user,
                    root=row.log_root,
                    **row.parameters,
                )
                row.state = "connecting"
                settings = self.app.state.settings
                timeout = (
                    settings.remote_lifetime_seconds
                    if kind in STREAM
                    else settings.remote_download_timeout
                    if kind in ("download", "search")
                    else settings.remote_read_timeout
                )
            factory = getattr(self.app.state, "remote_job_factory", RemoteJob)
            job = factory(
                config,
                req,
                password=password,
                auth_account=auth_account,
                timeout=timeout,
                connect_timeout=settings.remote_connect_timeout,
            )
            password = None
            config = None
            with self.lock:
                slot.job = job
                if slot.stopped:
                    return
            checked = 0
            while not self.stop_event.is_set() and not slot.stopped:
                if time.monotonic() - checked > 2:
                    checked = time.monotonic()
                    if not self.ensure_valid(sid):
                        break
                event = job.poll(0.05)
                with self.lock:
                    if slot.stopped:
                        break
                    if event and self._event(sid, slot, event, kind):
                        break
                if not event and not job.alive:
                    self.finish(sid, "failed", "worker_interrupted")
                    break
        except Exception:
            # Never log exception payloads: SSH errors may contain remote secrets.
            self.finish(sid, "failed", "worker_failed")
        finally:
            password = None
            if job:
                job.close()
            with self.lock:
                slot.job = None
                if slot.completed_at is None:
                    with self.app.state.session_factory() as db:
                        row = db.get(RemoteSession, sid)
                        if row and row.state not in ACTIVE:
                            self._complete_slot(slot)
                self._prune_completed()

    def _event(self, sid, slot, event, kind):
        et = event.get("type")
        if et == "ready":
            with self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                if row.state in ACTIVE:
                    row.state = "ready"
                    slot.attach_deadline = time.monotonic() + 30
        elif et == "files":
            files = event["files"][:1000]
            result = {
                "files": [{**f, "file_id": f"{sid}:{i}"} for i, f in enumerate(files)],
                "truncated": event.get("truncated", False),
            }
            with self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                if row.state in ACTIVE:
                    row.result = result
                    slot.result_bytes = len(json.dumps(result).encode("utf-8"))
        elif et == "search_progress":
            slot.result = {"progress": {key: value for key, value in event.items() if key != "type"}}
        elif et == "search":
            result = {key: value for key, value in event.items() if key != "type"}
            if len(json.dumps(result).encode("utf-8")) > 4 * 1048576:
                self.finish(sid, "failed", "output_limit")
                return True
            slot.result = result
            slot.result_bytes = len(json.dumps(result).encode("utf-8"))
        elif et == "text":
            if kind in STREAM:
                self.enqueue(sid, event)
            else:
                with self.lock:
                    previous = (slot.result or {}).get("text", "")
                    value = previous + event.get("text", "")
                    if len(value.encode("utf-8")) > 1048576:
                        self.finish(sid, "failed", "output_limit")
                        return True
                    slot.result = {**event, "text": value}
                    slot.result.pop("type", None)
                    slot.result_bytes = len(json.dumps(slot.result).encode("utf-8"))
        elif et == "download_start":
            size = event["size"]
            if not isinstance(size, int) or not 0 <= size <= 104857600:
                self.finish(sid, "failed", "download_limit")
                return True
            slot.tempdir = tempfile.TemporaryDirectory(prefix="dingofs-log-")
            slot.download = open(Path(slot.tempdir.name) / "content", "w+b")
            os.chmod(slot.download.name, 0o600)
            slot.download_size = size
        elif et == "download_chunk":
            data = event["data"]
            if (
                not slot.download
                or slot.download_received + len(data) > slot.download_size
            ):
                self.finish(sid, "failed", "download_limit")
                return True
            slot.download.write(data)
            slot.download_received += len(data)
        elif et == "auth":
            with self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                m = db.get(Machine, row.machine_id)
                account = event.get("account")
                if (
                    row.kind == "terminal"
                    or account not in {row.target_user, m.ssh_user}
                    or row.auth_attempts >= 3
                ):
                    self._finish_row(db, row, "failed", "authentication_failed")
                elif row.state in ACTIVE:
                    token = secrets.token_urlsafe(32)
                    row.state = "needs_password"
                    row.auth_account = account
                    row.auth_expires_at = now() + timedelta(seconds=300)
                    row.challenge_hash = digest(token)
                    slot.challenge = token
            return True
        elif et == "error":
            code = str(event.get("code", "worker_failed"))[:80]
            state = "failed"
            if code in {"host_key_unknown", "host_key_changed"} and event.get(
                "host_key"
            ):
                with self.app.state.session_factory.begin() as db:
                    row = db.get(RemoteSession, sid)
                    m = db.get(Machine, row.machine_id)
                    if m.revision == row.machine_revision:
                        if code == "host_key_changed":
                            m.revision += 1
                        m.ssh_trust_pending = make_challenge(m, event["host_key"])
                state = "needs_trust"
            self.finish(sid, state, code)
            return True
        elif et == "done":
            if kind == "download":
                if not slot.download or slot.download_received != slot.download_size:
                    self.finish(sid, "failed", "download_incomplete")
                    return True
                slot.download.flush()
                slot.download.close()
                slot.download = None
            if kind == "download":
                with self.app.state.session_factory.begin() as db:
                    row = db.get(RemoteSession, sid)
                    db.add(
                        AuditEvent(
                            actor=row.actor_id,
                            request_id="",
                            action="remote.download_ready",
                            entity="remote_sessions/" + sid,
                            detail={
                                "bytes": slot.download_received,
                                "machine_id": row.machine_id,
                                "service_id": row.service_id,
                            },
                        )
                    )
            self.finish(sid, "closed" if kind in STREAM else "succeeded")
            return True
        return False

    def _finish_row(self, db, row, state, code=None):
        if row.state not in ACTIVE and not (
            state == "closed" and row.state != "closed"
        ):
            return
        row.state = state
        row.error_code = code
        row.closed_at = now()
        row.challenge_hash = None
        if row.kind not in STREAM and state == "succeeded":
            row.expires_at = now() + timedelta(seconds=RESULT_TTL_SECONDS)
        db.add(
            AuditEvent(
                actor=row.actor_id,
                request_id="",
                action="remote." + state,
                entity="remote_sessions/" + row.id,
                detail={
                    "kind": row.kind,
                    "machine_id": row.machine_id,
                    "cluster_id": row.cluster_id,
                    "error_code": code,
                },
            )
        )

    def finish(self, sid, state, code=None):
        with self.lock:
            with self.app.state.session_factory.begin() as db:
                row = db.get(RemoteSession, sid)
                if row:
                    self._finish_row(db, row, state, code)
                completed = row is not None and row.state not in ACTIVE
            slot = self.slots.get(sid)
            if completed and slot:
                self._complete_slot(slot)
            if state in {"failed", "closed", "interrupted"}:
                self.enqueue(
                    sid,
                    {"type": "closed", "reason": code or state},
                    force=True,
                    discard=bool(code),
                )
            if state in {"failed", "interrupted", "needs_trust"} and slot:
                self._release_result(slot)
            self._prune_completed()

    def close(self, sid, reason="user_closed"):
        with self.lock:
            slot = self.slots.get(sid)
            if slot:
                slot.stopped = True
                if reason == "stream_disconnected":
                    slot.attached = False
                slot.challenge = None
                slot.result = None
                job = slot.job
            else:
                job = None
        if job:
            job.close()
        self.finish(sid, "closed", reason)
        with self.lock:
            if slot:
                self._release_result(slot)

    def ensure_valid(self, sid):
        with self.app.state.session_factory() as db:
            row = db.get(RemoteSession, sid)
            okay = bool(
                row
                and row.state not in {"closed", "failed", "interrupted"}
                and valid(db, row)
            )
            if okay and row.state == "needs_password":
                okay = bool(row.auth_expires_at and row.auth_expires_at > now())
        if not okay and row and row.state not in {"closed", "failed", "interrupted"}:
            self.close(sid, "authorization_expired")
        return okay

    def enqueue(self, sid, event, force=False, discard=False):
        with self.lock:
            slot = self.slots.get(sid)
            if not slot:
                return
            size = len(str(event).encode("utf-8"))
            if discard:
                slot.events.clear()
                slot.queued = 0
            if not force and (
                slot.queued + size > MAX_BUFFER or len(slot.events) >= 256
            ):
                self.close(sid, "slow_consumer")
                return
            slot.events.append((event, size))
            slot.queued += size

    def pop(self, sid):
        with self.lock:
            slot = self.slots.get(sid)
            if not slot or not slot.events:
                return None
            event, size = slot.events.popleft()
            slot.queued -= size
            return event

    def attach(self, sid):
        with self.lock:
            slot = self.slots.get(sid)
            if not slot or slot.stopped or slot.attached:
                return False
            slot.attached = True
            return True

    def send(self, sid, event):
        with self.lock:
            slot = self.slots.get(sid)
            if not slot or slot.stopped or not slot.job:
                return
            if event["type"] == "input":
                slot.last_input = time.monotonic()
            try:
                slot.job.send(event)
            except Exception:
                self.close(sid, "input_unavailable")

    def _sweep(self):
        while not self.stop_event.wait(1):
            with self.lock:
                pairs = list(self.slots.items())
            for sid, slot in pairs:
                try:
                    with self.app.state.session_factory() as db:
                        row = db.get(RemoteSession, sid)
                        if not row:
                            continue
                        active = row.state in ACTIVE
                        expired = row.expires_at <= now()
                        idle = (
                            row.kind == "terminal"
                            and time.monotonic() - slot.last_input
                            > self.app.state.settings.remote_idle_seconds
                        )
                        unattached = (
                            row.kind in STREAM
                            and row.state == "ready"
                            and not slot.attached
                            and time.monotonic() > slot.attach_deadline
                        )
                    if active:
                        if expired or idle or unattached:
                            self.close(sid, "session_timeout")
                        else:
                            self.ensure_valid(sid)
                    if expired or (not active and time.monotonic() > slot.expires):
                        self.close(sid, "expired")
                        with self.lock:
                            self._cleanup(slot)
                            self.slots.pop(sid, None)
                except Exception:
                    # Fail closed if the authorization store is unavailable.
                    with self.lock:
                        slot.stopped = True
                        if slot.job:
                            slot.job.close()
