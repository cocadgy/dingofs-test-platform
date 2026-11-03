"""Bounded password SSH upload; cleanup never masks the operation result."""
from contextlib import contextmanager
import secrets
import threading
import time
import paramiko


def safe_close(resource):
    if resource is not None:
        try:
            resource.close()
        except Exception:
            pass


@contextmanager
def upload_binary(config, artifact, cancelled, deadline):
    client, sftp, channel, created = paramiko.SSHClient(), None, None, False
    directory = "/tmp/dingofs-platform-binary-" + secrets.token_hex(20)
    path = directory + "/dingo-cache"
    stopped = threading.Event()
    interrupted = []
    def check(*args):
        if interrupted:
            raise ValueError(interrupted[0])
        if cancelled():
            raise ValueError("程序分发已取消")
        if time.monotonic() >= deadline:
            raise ValueError("程序分发超时")
    def watch():
        while not stopped.wait(0.1):
            try:
                check()
            except Exception as exc:
                interrupted.append(str(exc) or "程序分发已取消")
                safe_close(client)
                return
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        check()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        remaining = min(30, max(0.1, deadline - time.monotonic()))
        client.connect(hostname=config.host, port=config.port, username=config.username,
                       password=config.password, allow_agent=False, look_for_keys=False,
                       timeout=remaining, banner_timeout=remaining, auth_timeout=remaining)
        channel = client.get_transport().open_session(timeout=remaining)
        channel.settimeout(remaining)
        channel.invoke_subsystem("sftp")
        sftp = paramiko.SFTPClient(channel)
        check()
        sftp.mkdir(directory, mode=0o755)
        created = True
        sftp.chmod(directory, 0o755)
        sftp.put(artifact["path"], path, callback=check, confirm=True)
        sftp.chmod(path, 0o644)
        check()
        yield {"path": path, "sha256": artifact["sha256"]}
    except paramiko.AuthenticationException:
        check()
        raise ValueError("SSH 分发认证失败，请检查机器登录信息") from None
    except (paramiko.SSHException, OSError, EOFError):
        check()
        raise ValueError("SSH 分发程序失败，请检查目标机器连接、权限和磁盘空间") from None
    finally:
        if sftp and created and not interrupted:
            try:
                # Cleanup gets its own short bound, including subsystem stalls.
                deadline = min(deadline, time.monotonic() + 2)
                sftp.remove(path)
                sftp.rmdir(directory)
            except Exception:
                pass
        safe_close(sftp)
        safe_close(channel)
        safe_close(client)
        stopped.set()
        watcher.join(timeout=0.5)
