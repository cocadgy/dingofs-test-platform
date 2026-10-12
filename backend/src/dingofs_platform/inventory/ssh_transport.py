"""Bounded password SSH. DNS/auth/commands all run under one parent deadline."""

from dataclasses import dataclass, field, asdict
import json
import multiprocessing
import socket
import time
import paramiko
from .host_trust import key_info


@dataclass(frozen=True)
class SSHConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    known_hosts: str = ""
    trusted_host_key: dict | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


ERRORS = {
    "timeout": "SSH 采集超时，请检查网络或机器负载",
    "output_limit": "采集输出超过大小限制",
    "host_key_unknown": "SSH 主机尚未受信任，请核验下方指纹并确认",
    "host_key_changed": "SSH 主机密钥已变化，已停止连接，请核验新旧指纹",
    "known_hosts_missing": "SSH known_hosts 文件不存在或无法读取",
    "authentication_failed": "SSH 认证失败，请核对用户名和密码",
    "connection_failed": "SSH 连接失败，请检查地址、端口和网络",
    "worker_failed": "采集进程异常退出，请重试",
}


class CollectionError(Exception):
    def __init__(self, code, host_key=None):
        self.host_key = host_key
        self.code = code if code in ERRORS else "worker_failed"
        super().__init__(self.code)


class RejectUnknownHost(paramiko.RejectPolicy):
    def missing_host_key(self, client, hostname, key):
        raise CollectionError("host_key_unknown", host_key=key_info(key))


def run_session(
    config, commands, timeout_s, max_bytes, *, client_factory=paramiko.SSHClient
):
    client = client_factory()
    deadline = time.monotonic() + timeout_s
    count = 0

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise CollectionError("timeout")
        return value

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
            timeout=remaining(),
            banner_timeout=remaining(),
            auth_timeout=remaining(),
            channel_timeout=remaining(),
        )
        results = {}
        for name, command in commands.items():
            channel = client.get_transport().open_session(timeout=remaining())
            try:
                channel.settimeout(remaining())
                channel.exec_command("LC_ALL=C; export LC_ALL; " + command)
                channel.shutdown_write()
                out, err = bytearray(), bytearray()
                while True:
                    remaining()
                    ready = False
                    for available, read, buffer in [
                        (channel.recv_ready, channel.recv, out),
                        (channel.recv_stderr_ready, channel.recv_stderr, err),
                    ]:
                        if available():
                            chunk = read(min(65536, max_bytes - count + 1))
                            count += len(chunk)
                            if count > max_bytes:
                                raise CollectionError("output_limit")
                            buffer.extend(chunk)
                            ready = True
                    if (
                        channel.exit_status_ready()
                        and not channel.recv_ready()
                        and not channel.recv_stderr_ready()
                    ):
                        break
                    if not ready:
                        time.sleep(min(0.02, remaining()))
                results[name] = CommandResult(
                    out.decode("utf-8", errors="replace"),
                    err.decode("utf-8", errors="replace"),
                    channel.recv_exit_status(),
                )
            finally:
                channel.close()
        return results
    except paramiko.BadHostKeyException as exc:
        details = key_info(exc.key) if exc.key is not None else None
        if details is not None:
            details["previous_fingerprint"] = (
                key_info(exc.expected_key)["fingerprint"]
                if exc.expected_key is not None
                else None
            )
        raise CollectionError("host_key_changed", host_key=details) from None
    except paramiko.AuthenticationException:
        raise CollectionError("authentication_failed") from None
    except (TimeoutError, socket.timeout):
        raise CollectionError("timeout") from None
    except (OSError, paramiko.SSHException):
        raise CollectionError("connection_failed") from None
    finally:
        client.close()


def _worker(config, commands, timeout_s, max_bytes, send):
    # Child logs must never contain a password or untrusted server error text.
    import logging

    logging.disable(logging.CRITICAL)
    try:
        results = run_session(config, commands, timeout_s, max_bytes)
        payload = {"results": {k: asdict(v) for k, v in results.items()}}
        encoded = json.dumps(payload, ensure_ascii=True).encode()
        if len(encoded) > max_bytes:
            raise CollectionError("output_limit")
    except CollectionError as exc:
        encoded = json.dumps({"error": exc.code, "host_key": exc.host_key}).encode()
    except Exception:
        encoded = b'{"error":"worker_failed"}'
    try:
        send.send_bytes(encoded)
    finally:
        send.close()


def supervise(config, commands, timeout_s, max_bytes, *, worker=_worker):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=worker, args=(config, commands, timeout_s, max_bytes, send), daemon=True
    )
    deadline = time.monotonic() + timeout_s
    started = False
    try:
        process.start()
        started = True
        send.close()
        if not receive.poll(max(0, deadline - time.monotonic())):
            raise CollectionError("timeout")
        try:
            payload = json.loads(receive.recv_bytes(maxlength=max_bytes))
        except OSError:
            raise CollectionError("output_limit") from None
        except (EOFError, ValueError):
            raise CollectionError("worker_failed") from None
        if "error" in payload:
            raise CollectionError(payload["error"], host_key=payload.get("host_key"))
        return {
            name: CommandResult(**value) for name, value in payload["results"].items()
        }
    finally:
        receive.close()
        send.close()
        if started:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.5)
            if not process.is_alive():
                process.close()


def execute(config, commands, timeout_s=30, max_bytes=1048576):
    return supervise(config, commands, timeout_s, max_bytes)
