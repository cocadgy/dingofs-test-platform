"""Bounded SSH processes for read-only logs and explicit interactive terminals."""

import base64
import codecs
import json
import logging
import multiprocessing
import queue
import re
import secrets
import shlex
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import paramiko

from dingofs_platform.inventory.host_trust import key_info
from dingofs_platform.inventory.ssh_transport import CollectionError

from . import log_helper

QUEUE_SIZE = 16
MAX_WIRE = 8 * 1048576
USER = re.compile(r"[a-zA-Z0-9_.-]{1,80}\Z")


@dataclass(frozen=True)
class RemoteRequest:
    kind: str
    target_user: str
    root: str | None = None
    name: str | None = None
    keyword: str | None = None
    case_sensitive: bool = False
    lines: int = 500
    cursor: dict | None = None
    cols: int = 100
    rows: int = 30

    def __post_init__(self):
        if self.kind not in (
            "files",
            "search",
            "read",
            "download",
            "log-follow",
            "terminal",
        ) or not USER.fullmatch(self.target_user):
            raise ValueError("invalid request")
        if type(self.lines) is not int or not 1 <= self.lines <= 1000:
            raise ValueError("invalid lines")
        if any(
            type(value) is not int or not 1 <= value <= 500
            for value in (self.cols, self.rows)
        ):
            raise ValueError("invalid dimensions")
        if self.kind == "terminal":
            if (
                self.root is not None
                or self.name is not None
                or self.cursor is not None
            ):
                raise ValueError("unexpected log parameters")
        else:
            if (
                not isinstance(self.root, str)
                or not self.root.startswith("/")
                or "\x00" in self.root
                or len(self.root) > 4096
            ):
                raise ValueError("invalid directory")
            if self.kind not in ("files", "search"):
                try:
                    log_helper.leaf(self.name)
                except log_helper.LogError:
                    raise ValueError("invalid file") from None
            elif self.name is not None:
                raise ValueError("unexpected file")
            if self.kind == "search" and (not isinstance(self.keyword, str) or not self.keyword.strip() or len(self.keyword) > 200):
                raise ValueError("invalid keyword")
        if self.cursor is not None and (
            not isinstance(self.cursor, dict)
            or set(self.cursor) != {"device", "inode", "offset"}
            or any(
                type(value) is not int or value < 0 or value > 2**64 - 1
                for value in self.cursor.values()
            )
        ):
            raise ValueError("invalid cursor")


class RemoteError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class AuthRequired(RemoteError):
    def __init__(self, account):
        self.account = account
        super().__init__("needs_password")


def build_command(
    request, ssh_user, nonce, interactive=False, max_download=log_helper.MAX_DOWNLOAD
):
    if request.kind == "terminal":
        raise ValueError("terminal uses invoke_shell")
    parameters = dict(
        asdict(request), max_download=min(max_download, log_helper.MAX_DOWNLOAD)
    )
    source = Path(log_helper.__file__).read_text()
    program = (
        "exec python3 -c "
        + shlex.quote(source)
        + " "
        + shlex.quote(json.dumps(parameters, ensure_ascii=True))
    )
    if request.target_user == ssh_user:
        return program
    options = (
        "-S -p " + shlex.quote("__DTT_REMOTE_AUTH_" + nonce + "__%p__END__")
        if interactive
        else "-n"
    )
    return (
        "LC_ALL=C sudo "
        + options
        + " -u "
        + shlex.quote(request.target_user)
        + " -- sh -c "
        + shlex.quote(program)
    )


def _redact(event, passwords):
    if isinstance(event, str):
        for password in passwords:
            if password:
                event = event.replace(password, "[REDACTED]")
        return event
    if isinstance(event, dict):
        return {key: _redact(value, passwords) for key, value in event.items()}
    if isinstance(event, list):
        return [_redact(value, passwords) for value in event]
    return event


def _log_channel(channel, emit, nonce, password, account, deadline, passwords):
    output = bytearray()
    errors = bytearray()
    started = False
    ended = False
    sent = False
    scan = 0
    pattern = re.compile(
        re.escape("__DTT_REMOTE_AUTH_" + nonce + "__")
        + r"([a-zA-Z0-9_.-]{1,80})__END__"
    )
    while True:
        if time.monotonic() >= deadline:
            raise RemoteError("timeout")
        active = False
        if channel.recv_ready():
            output.extend(channel.recv(65536))
            active = True
            if len(output) > MAX_WIRE:
                raise RemoteError("output_limit")
            while b"\n" in output:
                line, _, tail = output.partition(b"\n")
                output = bytearray(tail)
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get("type") not in (
                        "ready",
                        "files",
                        "search",
                        "search_progress",
                        "text",
                        "download_start",
                        "download_chunk",
                        "done",
                        "error",
                    ):
                        raise ValueError()
                    if event["type"] == "ready":
                        started = True
                        # No further input is sent after the helper starts.
                        channel.shutdown_write()
                    elif not started and event["type"] != "error":
                        raise ValueError()
                    if event["type"] == "download_chunk":
                        event["data"] = base64.b64decode(event["data"], validate=True)
                        if len(event["data"]) > 65536:
                            raise ValueError()
                    if event["type"] in ("done", "error"):
                        ended = True
                    emit(_redact(event, passwords))
                except (ValueError, KeyError, TypeError):
                    raise RemoteError("invalid_protocol") from None
        if channel.recv_stderr_ready():
            errors.extend(channel.recv_stderr(16384))
            active = True
            if len(errors) > 65536:
                raise RemoteError("output_limit")
        if not started:
            text = errors.decode("utf8", errors="replace")
            match = pattern.search(text, scan)
            if match:
                scan = match.end()
                if password is None or sent:
                    raise AuthRequired(match[1])
                if match[1] != account:
                    raise RemoteError("auth_account_changed")
                channel.sendall((password + "\n").encode())
                channel.shutdown_write()
                sent = True
        if (
            channel.exit_status_ready()
            and not channel.recv_ready()
            and not channel.recv_stderr_ready()
        ):
            if started and not ended:
                raise RemoteError("connection_lost")
            return (
                started or ended,
                channel.recv_exit_status(),
                errors.decode("utf8", errors="replace"),
            )
        if not active:
            time.sleep(0.01)


def _terminal(channel, request, emit, receive, deadline):
    channel.get_pty(term="xterm-256color", width=request.cols, height=request.rows)
    channel.invoke_shell()
    decoder = codecs.getincrementaldecoder("utf8")("replace")
    emit({"type": "ready"})
    while True:
        if time.monotonic() >= deadline:
            raise RemoteError("timeout")
        message = receive()
        if message is not None:
            if message["type"] == "input":
                channel.sendall(message["data"].encode())
            elif message["type"] == "resize":
                channel.resize_pty(width=message["cols"], height=message["rows"])
        active = message is not None
        for ready, read in (
            (channel.recv_ready, channel.recv),
            (channel.recv_stderr_ready, channel.recv_stderr),
        ):
            if ready():
                text = decoder.decode(read(65536))
                if text:
                    emit({"type": "text", "text": text})
                active = True
        if (
            channel.exit_status_ready()
            and not channel.recv_ready()
            and not channel.recv_stderr_ready()
        ):
            tail = decoder.decode(b"", final=True)
            if tail:
                emit({"type": "text", "text": tail})
            emit({"type": "done"})
            return
        if not active:
            time.sleep(0.01)


def run_session(
    config,
    request,
    emit,
    receive,
    *,
    password=None,
    auth_account=None,
    connect_timeout=15,
    timeout=30,
    max_download=log_helper.MAX_DOWNLOAD,
    connected=lambda: None,
    client_factory=paramiko.SSHClient,
):
    if request.kind == "terminal" and request.target_user != config.username:
        raise ValueError("terminal identity must equal SSH login")
    client = client_factory()
    deadline = time.monotonic() + timeout
    try:
        # Platform policy: trust SSH host keys automatically on every connection.
        # Do not load historical pins or known_hosts requiring user confirmation.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        seconds = min(timeout, connect_timeout)
        client.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            allow_agent=False,
            look_for_keys=False,
            timeout=seconds,
            banner_timeout=seconds,
            auth_timeout=seconds,
            channel_timeout=seconds,
        )
        connected()
        nonce = secrets.token_hex(24)
        for interactive in (False, True):
            channel = client.get_transport().open_session(
                timeout=max(0.001, min(connect_timeout, deadline - time.monotonic()))
            )
            try:
                channel.settimeout(max(0.001, deadline - time.monotonic()))
                if request.kind == "terminal":
                    _terminal(channel, request, emit, receive, deadline)
                    return
                channel.exec_command(
                    build_command(
                        request, config.username, nonce, interactive, max_download
                    )
                )
                if not interactive:
                    channel.shutdown_write()
                complete, _rc, diagnostic = _log_channel(
                    channel,
                    emit,
                    nonce,
                    password if interactive else None,
                    auth_account,
                    deadline,
                    (config.password, password),
                )
            finally:
                channel.close()
            if complete:
                return
            lower = diagnostic.lower()
            if "unknown user" in lower or "user does not exist" in lower:
                raise RemoteError("user_missing")
            if "python3: not found" in lower or "python3: command not found" in lower:
                raise RemoteError("python_missing")
            if "sudo: not found" in lower or "sudo: command not found" in lower:
                raise RemoteError("sudo_missing")
            if (
                not interactive
                and request.target_user != config.username
                and "a password is required" in lower
            ):
                continue
            raise RemoteError(
                "switch_denied"
                if request.target_user != config.username
                else "remote_failed"
            )
    except paramiko.BadHostKeyException as exc:
        details = key_info(exc.key)
        details["previous_fingerprint"] = key_info(exc.expected_key)["fingerprint"]
        raise CollectionError("host_key_changed", host_key=details) from None
    except paramiko.AuthenticationException:
        raise RemoteError("authentication_failed") from None
    except TimeoutError:
        raise RemoteError("timeout") from None
    except (OSError, paramiko.SSHException):
        raise RemoteError("connection_failed") from None
    finally:
        client.close()


class Emitter:
    def __init__(self, output, failure):
        self.output = output
        self.failure = failure

    def __call__(self, event):
        try:
            self.output.put(event, timeout=0.5)
        except queue.Full:
            self.failure.value = 1
            raise RemoteError("slow_consumer") from None


def _worker(
    output,
    incoming,
    failure,
    connected,
    config,
    request,
    password,
    auth_account,
    connect_timeout,
    timeout,
    max_download,
):
    logging.disable(logging.CRITICAL)
    emit = Emitter(output, failure)

    def receive():
        try:
            return incoming.get_nowait()
        except queue.Empty:
            return None

    try:
        run_session(
            config,
            request,
            emit,
            receive,
            password=password,
            auth_account=auth_account,
            connect_timeout=connect_timeout,
            timeout=timeout,
            max_download=max_download,
            connected=connected.set,
        )
    except AuthRequired as exc:
        event = {"type": "auth", "account": exc.account}
    except CollectionError as exc:
        event = {"type": "error", "code": exc.code, "host_key": exc.host_key}
    except RemoteError as exc:
        event = {"type": "error", "code": exc.code}
    except Exception:  # noqa: BLE001 - child boundary must not expose remote secrets
        event = {"type": "error", "code": "worker_failed"}
    else:
        return
    if not failure.value:
        try:
            emit(event)
        except RemoteError:
            pass


class RemoteJob:
    def __init__(
        self,
        config,
        request,
        *,
        password=None,
        auth_account=None,
        connect_timeout=15,
        timeout=30,
        max_download=log_helper.MAX_DOWNLOAD,
    ):
        if request.kind == "terminal" and request.target_user != config.username:
            raise ValueError("terminal identity must equal SSH login")
        if password is not None and (
            not isinstance(password, str)
            or "\n" in password
            or "\r" in password
            or len(password) > 4096
        ):
            raise ValueError("invalid password")
        self.request = request
        self._lifecycle = threading.RLock()
        ctx = multiprocessing.get_context("spawn")
        self._output = ctx.Queue(maxsize=QUEUE_SIZE)
        self._incoming = ctx.Queue(maxsize=QUEUE_SIZE)
        self._failure = ctx.Value("i", 0)
        self._connected = ctx.Event()
        self._closed = False
        self._deadline = time.monotonic() + timeout
        self._connect_deadline = time.monotonic() + connect_timeout
        self._process = ctx.Process(
            target=_worker,
            args=(
                self._output,
                self._incoming,
                self._failure,
                self._connected,
                config,
                request,
                password,
                auth_account,
                connect_timeout,
                timeout,
                max_download,
            ),
            daemon=True,
        )
        try:
            self._process.start()
        except Exception:
            self.close()
            raise

    @property
    def alive(self):
        with self._lifecycle:
            return not self._closed and self._process.is_alive()

    def poll(self, timeout=0.05):
        with self._lifecycle:
            if self._closed:
                return None
            if self._failure.value:
                self.close()
                return {"type": "error", "code": "slow_consumer"}
            if (
                time.monotonic() >= self._deadline
                or not self._connected.is_set()
                and time.monotonic() >= self._connect_deadline
            ):
                self.close()
                return {"type": "error", "code": "timeout"}
            try:
                event = self._output.get(timeout=max(0, min(timeout, 0.05)))
            except queue.Empty:
                if not self.alive:
                    self.close()
                    return {"type": "error", "code": "worker_failed"}
                return None
            if event.get("type") in ("done", "auth", "error"):
                self.close()
            return event

    def send(self, message):
        with self._lifecycle:
            if (
                self.request.kind != "terminal"
                or self._closed
                or not isinstance(message, dict)
            ):
                raise ValueError("terminal input unavailable")
            kind = message.get("type")
            if kind == "input":
                if (
                    set(message) != {"type", "data"}
                    or not isinstance(message["data"], str)
                    or len(message["data"].encode()) > 16384
                ):
                    raise ValueError("invalid input")
            elif kind == "resize":
                if set(message) != {"type", "cols", "rows"} or any(
                    type(message[key]) is not int or not 1 <= message[key] <= 500
                    for key in ("cols", "rows")
                ):
                    raise ValueError("invalid dimensions")
            else:
                raise ValueError("invalid message")
            try:
                self._incoming.put_nowait(dict(message))
            except queue.Full:
                self._failure.value = 1
                raise RemoteError("slow_consumer") from None

    def close(self):
        with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            if self._process.pid is not None:
                self._process.join(0.05)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(0.2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(0.5)
                if not self._process.is_alive():
                    self._process.close()
            for stream in (self._output, self._incoming):
                stream.cancel_join_thread()
                stream.close()
