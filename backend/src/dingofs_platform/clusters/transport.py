"""Fixed read-only dingo actions, supervised SSH and one-shot sudo authentication."""

from dataclasses import dataclass, asdict
import json
import logging
import multiprocessing
import re
import secrets
import shlex
import socket
import time
import paramiko
from dingofs_platform.inventory.ssh_transport import CollectionError
from dingofs_platform.inventory.host_trust import key_info
from .parser import NAME

CONTROL_ACTIONS = ("start", "stop", "restart")
USER = re.compile(r"[a-zA-Z0-9_.-]{1,80}\Z")


class ClusterExecutionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class AuthenticationRequired(ClusterExecutionError):
    def __init__(self, account):
        self.account = account
        super().__init__("needs_password")


@dataclass(frozen=True)
class ClusterCommand:
    kind: str
    target_user: str
    cluster_name: str | None = None
    scope: str | None = None
    target: str | None = None
    expected_home: str | None = None
    resource_script: str | None = None
    resource_requires_dingo: bool = True

    def __post_init__(self):
        if self.kind not in (
            "discover",
            "status",
            "topology",
            "resource",
            *CONTROL_ACTIONS,
        ) or not USER.fullmatch(self.target_user):
            raise ValueError("invalid action")
        if self.kind != "resource" and not self.resource_requires_dingo:
            raise ValueError("runtime override only applies to resource commands")
        if (self.kind == "resource") != bool(self.resource_script):
            raise ValueError("invalid resource command")
        if self.kind != "discover" and not NAME.fullmatch(self.cluster_name or ""):
            raise ValueError("invalid cluster name")
        if self.kind == "discover" and self.cluster_name is not None:
            raise ValueError("unexpected cluster")
        if self.kind in CONTROL_ACTIONS:
            if self.scope not in ("all", "service", "role"):
                raise ValueError("invalid scope")
            if self.scope == "all":
                if self.target is not None:
                    raise ValueError("unexpected target")
            elif not NAME.fullmatch(self.target or ""):
                raise ValueError("invalid target")
        elif self.scope is not None or self.target is not None:
            raise ValueError("unexpected target")


@dataclass(frozen=True)
class ExecutionIdentity:
    user: str
    home: str
    dingo_path: str


@dataclass(frozen=True)
class ClusterCommandResult:
    identity: ExecutionIdentity
    stdout: str
    stderr: str
    returncode: int


def operation_command(command):
    q = shlex.quote
    query = (
        "dingo config show"
        if command.kind == "topology"
        else "dingo cluster status -sv"
    )
    if command.kind in CONTROL_ACTIONS:
        flag = (
            ""
            if command.scope == "all"
            else (" --id " if command.scope == "service" else " --role ")
            + q(command.target)
        )
        query = f"dingo cluster {command.kind}{flag} --force"
    action = (
        "unset dingo_cluster; dingo cluster ls"
        if command.kind == "discover"
        else f"export dingo_cluster={q(command.cluster_name)}; {query}"
    )
    if command.kind == "resource":
        action = f"export dingo_cluster={q(command.cluster_name)}; " + command.resource_script
    return action


def build_command(command, ssh_user, nonce, interactive):
    q = shlex.quote
    home_check = (
        f'test "$HOME" = {q(command.expected_home)} || exit 92'
        if command.expected_home
        else ":"
    )
    action = operation_command(command)
    # sudo -i re-quotes the command through the target login shell. Literal
    # newlines can lose their separator semantics; use explicit shell separators.
    script = "; ".join(
        [
            f'test "$(id -un)" = {q(command.target_user)} || exit 92',
            home_check,
            "p=$(command -v dingo) || exit 91" if command.resource_requires_dingo else "p=$(command -v python3) || exit 93",
            f"""printf '%s\\n' '__DTT_BEGIN_{nonce}__' "$(id -un)" "$HOME" "$p" '__DTT_OUTPUT_{nonce}__'""",
            f"printf '%s\\n' '__DTT_STDERR_{nonce}__' >&2",
            action,
        ]
    )
    if ssh_user == command.target_user:
        return "bash -lc " + q(script)
    opts = f"-S -p {q('__DTT_AUTH_' + nonce + '__%p__END__')}" if interactive else "-n"
    if command.target_user == "root":
        # Match the operator's sudo su - workflow. Avoid sudo -i's extra shell
        # re-quoting, which can also expand script variables before assignment.
        return f"LC_ALL=C sudo {opts} -u root -- su - root -c " + q(script)
    # Set the target HOME and let bash load its login profile directly.
    # sudo -i adds an extra shell expansion that can empty the dingo path.
    return f"LC_ALL=C sudo {opts} -H -u {q(command.target_user)} -- bash -lc " + q(script)


def read_channel(channel, nonce, password, account, timeout_s, max_bytes):
    deadline = time.monotonic() + timeout_s
    out = bytearray()
    err = bytearray()
    sent = False
    scan = 0
    pattern = re.compile(
        re.escape("__DTT_AUTH_" + nonce + "__") + r"([a-zA-Z0-9_.-]{1,80})__END__"
    )
    while True:
        if time.monotonic() >= deadline:
            raise ClusterExecutionError("timeout")
        active = False
        for ready, read, buf in [
            (channel.recv_ready, channel.recv, out),
            (channel.recv_stderr_ready, channel.recv_stderr, err),
        ]:
            if ready():
                buf.extend(read(min(65536, max_bytes - len(out) - len(err) + 1)))
                active = True
                if len(out) + len(err) > max_bytes:
                    raise ClusterExecutionError("output_limit")
        # Authentication only exists before command framing. Never feed a running dingo process.
        if ("__DTT_BEGIN_" + nonce + "__").encode() not in out:
            text = err.decode("utf8", errors="replace")
            match = pattern.search(text, scan)
            if match:
                scan = match.end()
                if password is None or sent:
                    raise AuthenticationRequired(match[1])
                if match[1] != account:
                    raise ClusterExecutionError("auth_account_changed")
                channel.sendall((password + "\n").encode())
                channel.shutdown_write()
                sent = True
        if (
            channel.exit_status_ready()
            and not channel.recv_ready()
            and not channel.recv_stderr_ready()
        ):
            break
        if not active:
            time.sleep(0.01)
    return (
        out.decode("utf8", errors="replace"),
        err.decode("utf8", errors="replace"),
        channel.recv_exit_status(),
    )


def run_session(
    config,
    command,
    password=None,
    auth_account=None,
    timeout_s=60,
    max_bytes=2097152,
    client_factory=paramiko.SSHClient,
):
    deadline = time.monotonic() + timeout_s

    def left():
        n = deadline - time.monotonic()
        if n <= 0:
            raise ClusterExecutionError("timeout")
        return n

    client = client_factory()
    try:
        # Platform policy: trust SSH host keys automatically on every connection.
        # Do not load historical pins or known_hosts requiring user confirmation.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            allow_agent=False,
            look_for_keys=False,
            timeout=left(),
            banner_timeout=left(),
            auth_timeout=left(),
            channel_timeout=left(),
        )
        nonce = secrets.token_hex(24)
        for interactive in [False, True]:
            channel = client.get_transport().open_session(timeout=left())
            try:
                channel.settimeout(left())
                channel.exec_command(
                    build_command(command, config.username, nonce, interactive)
                )
                if not interactive:
                    channel.shutdown_write()
                stdout, stderr, rc = read_channel(
                    channel,
                    nonce,
                    password if interactive else None,
                    auth_account,
                    left(),
                    max_bytes,
                )
            finally:
                channel.close()
            marker = "__DTT_BEGIN_" + nonce + "__\n"
            if marker in stdout:
                identity, sep, output = stdout.split(marker, 1)[1].partition(
                    "__DTT_OUTPUT_" + nonce + "__\n"
                )
                fields = identity.rstrip("\n").splitlines()
                if (
                    not sep
                    or len(fields) != 3
                    or fields[0] != command.target_user
                    or not fields[1].startswith("/")
                    or not fields[2].startswith("/")
                ):
                    raise ClusterExecutionError("invalid_identity")
                stderr_marker = "__DTT_STDERR_" + nonce + "__\n"
                diagnostic = (
                    stderr.split(stderr_marker, 1)[1] if stderr_marker in stderr else ""
                )
                # Only command output is returned; pre-auth stderr is intentionally discarded.
                for secret in (config.password, password):
                    if secret:
                        output = output.replace(secret, "[REDACTED]")
                        diagnostic = diagnostic.replace(secret, "[REDACTED]")
                return ClusterCommandResult(
                    ExecutionIdentity(*fields), output, diagnostic, rc
                )
            if rc == 93:
                raise ClusterExecutionError("python_missing")
            if rc == 91:
                raise ClusterExecutionError("dingo_missing")
            if rc == 92:
                raise ClusterExecutionError("invalid_identity")
            low = stderr.lower()
            if "unknown user" in low or "user does not exist" in low:
                raise ClusterExecutionError("user_missing")
            if "sudo: command not found" in low or "sudo: not found" in low:
                raise ClusterExecutionError("sudo_missing")
            if (
                not interactive
                and command.target_user != config.username
                and "a password is required" in low
            ):
                continue
            raise ClusterExecutionError(
                "switch_denied"
                if command.target_user != config.username
                else "login_failed"
            )
        raise ClusterExecutionError("switch_denied")
    except paramiko.BadHostKeyException as exc:
        details = key_info(exc.key)
        details["previous_fingerprint"] = key_info(exc.expected_key)["fingerprint"]
        raise CollectionError("host_key_changed", host_key=details) from None
    except paramiko.AuthenticationException:
        raise ClusterExecutionError("authentication_failed") from None
    except (socket.timeout, TimeoutError):
        raise ClusterExecutionError("timeout") from None
    except (OSError, paramiko.SSHException):
        raise ClusterExecutionError("connection_failed") from None
    finally:
        client.close()


def _worker(send, config, command, password, account, timeout, max_bytes):
    logging.disable(logging.CRITICAL)
    try:
        payload = {
            "result": asdict(
                run_session(config, command, password, account, timeout, max_bytes)
            )
        }
    except AuthenticationRequired as e:
        payload = {"error": "needs_password", "account": e.account}
    except CollectionError as e:
        payload = {"error": e.code, "host_key": e.host_key}
    except ClusterExecutionError as e:
        payload = {"error": e.code}
    except Exception:
        payload = {"error": "worker_failed"}
    try:
        send.send_bytes(json.dumps(payload).encode())
    finally:
        send.close()


def execute_cluster(
    config,
    command,
    *,
    password=None,
    auth_account=None,
    timeout_s=60,
    max_bytes=2097152,
    cancelled=lambda: False,
):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_worker,
        args=(send, config, command, password, auth_account, timeout_s, max_bytes),
        daemon=True,
    )
    deadline = time.monotonic() + timeout_s
    started = False
    try:
        if cancelled():
            raise ClusterExecutionError("cancelled")
        process.start()
        started = True
        send.close()
        while not receive.poll(0.1):
            if cancelled():
                raise ClusterExecutionError("cancelled")
            if time.monotonic() >= deadline:
                raise ClusterExecutionError("timeout")
            if not process.is_alive():
                raise ClusterExecutionError("worker_failed")
        if cancelled():
            raise ClusterExecutionError("cancelled")
        # The SSH byte limit is enforced by read_channel. The IPC envelope
        # JSON-encodes that text again (a control byte can become six ASCII
        # bytes), so its bounded framing allowance must include this expansion.
        payload = json.loads(receive.recv_bytes(maxlength=6 * max_bytes + 65536))
        if payload.get("error") == "needs_password":
            raise AuthenticationRequired(payload["account"])
        if payload.get("host_key"):
            raise CollectionError(payload["error"], host_key=payload["host_key"])
        if payload.get("error"):
            raise ClusterExecutionError(payload["error"])
        result = payload["result"]
        result["identity"] = ExecutionIdentity(**result["identity"])
        return ClusterCommandResult(**result)
    except (EOFError, OSError, ValueError):
        raise ClusterExecutionError("worker_failed") from None
    finally:
        receive.close()
        send.close()
        if started:
            process.join(0.1)
            if process.is_alive():
                process.terminate()
                process.join(0.2)
            if process.is_alive():
                process.kill()
                process.join(0.5)
            if not process.is_alive():
                process.close()
