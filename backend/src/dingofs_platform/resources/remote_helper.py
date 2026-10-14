"""Standalone bounded resource helper, transmitted as source to the target user.

All child commands use argument arrays. Lifecycle state is private to the target
account, and signals require the recorded executable, argv and Linux start time.
"""

import fcntl
import socket
import shlex
import shutil
import errno
import json
import os
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

MAX_OUTPUT = 1024 * 1024
# Each filesystem may contain 1024 pretty-printed hash bucket IDs. Even a
# modest list can exceed the normal command allowance; keep this read bounded
# separately, and leave stderr and all other actions at the normal allowance.
FS_LIST_MAX_OUTPUT = 32 * 1024 * 1024
# Allow room for the helper/SSH envelopes and bounded stderr as well.
FS_LIST_MAX_RESPONSE = FS_LIST_MAX_OUTPUT + 2 * MAX_OUTPUT
SECRET_KEYS = {
    "s3ak",
    "s3sk",
    "accesskey",
    "secretkey",
    "accesskeyid",
    "secretaccesskey",
    "radoskey",
    "password",
    "key",
    "ak",
    "sk",
}


def redact(value, secrets=(), *, show_storage_keys=False):
    if isinstance(value, dict):
        return {
            key: item
            if show_storage_keys and key.lower() in {"ak", "sk"}
            else "[REDACTED]"
            if re.sub(r"[^a-z0-9]", "", key.lower()) in SECRET_KEYS
            else redact(item, secrets, show_storage_keys=show_storage_keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets, show_storage_keys=show_storage_keys) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        # Text CLI variants can print nested JSON preceded by diagnostic lines.
        value = re.sub(
            r'(?i)(["\x27]?(?:access_?key(?:_?id)?|secret_?(?:access_?)?key|s3[._]a?k|s3[._]sk|rados[._]key|password|ak|sk)["\x27]?\s*[:=]\s*)(["\x27])[^"\x27\r\n]*\2',
            r'\1"[REDACTED]"',
            value,
        )
        value = re.sub(
            r'(?i)(["\x27]?(?:access_?key(?:_?id)?|secret_?(?:access_?)?key|s3[._](?:ak|sk)|rados[._]key|password|key|ak|sk)["\x27]?\s*[:=]\s*)(?:["\x27][^"\x27\r\n]*["\x27]|[^,\r\n}\s]+)',
            r'\1"[REDACTED]"',
            value,
        )
    return value


def check_json(value):
    if not isinstance(value, dict):
        raise ValueError("invalid command JSON response")  # noqa: TRY004 - command failure contract
    error = value.get("error") or {}
    result = value.get("result") or {}
    business = result.get("error") or {} if isinstance(result, dict) else {}
    reasons = []
    if isinstance(business, dict) and business.get("errcode", 0) not in (
        0,
        "0",
        None,
        "OK",
    ):
        code = business.get("errcode")
        message = str(business.get("errmsg") or "command business error")
        hint = (
            "（文件系统仍有挂载登记，请先核实并卸载客户端）"
            if message.strip() == "fs exist mount point."
            else ""
        )
        reasons.append(f"MDS [{code}]: {message}{hint}")
    if isinstance(error, dict) and error.get("code", 0) not in (0, "0", None):
        message = (
            error.get("description") or error.get("message") or "command API error"
        )
        reasons.append(f"CLI [{error.get('code')}]: {message}")
    if reasons:
        raise ValueError("; ".join(reasons)[:8192])

    return value


class CommandFailure(ValueError):
    """A completed CLI command reported failure."""


COMMAND_TRACE = []
TRACE_ENABLED = False


def traced_signal(expected, method, send, sig=signal.SIGTERM):
    entry = {"command": "kill {} -- {}".format("-9" if sig == signal.SIGKILL else "-TERM", expected["pid"]),
             "method": method, "executable": expected["exe"],
             "status": "attempted", "count": 1, "equivalent": True, "signal": signal.Signals(sig).name}
    if TRACE_ENABLED:
        COMMAND_TRACE.append(entry)
    send()
    entry["status"] = "started"


def traced_popen(argv, **kwargs):
    entry = None
    if TRACE_ENABLED:
        command = " ".join(shlex.quote(str(arg)) for arg in argv)
        # Repeated readiness queries are collapsed; do not lose the launcher.
        if COMMAND_TRACE and COMMAND_TRACE[-1]["command"] == command:
            entry = COMMAND_TRACE[-1]
            entry["count"] += 1
        elif len(COMMAND_TRACE) < 64:
            entry = {"command": command[:16384], "truncated": len(command) > 16384,
                     "executable": shutil.which(str(argv[0])) or str(argv[0]),
                     "status": "attempted", "count": 1}
            COMMAND_TRACE.append(entry)
    process = subprocess.Popen(argv, **kwargs)
    if entry is not None:
        entry["status"] = "started"
    return process



def prepare_mds_command(req, argv):
    """Resolve the target user's MDS CLI and one reachable cluster endpoint.

    Do not retry mutations after launch: their outcome could be unknown.
    """
    program = argv[0]
    if program == "dingo-mds-client":
        homes = [Path.home()]
        if req.get("tool_home"):
            homes.append(Path(req["tool_home"]))
        candidates = [shutil.which(program)]
        for home in homes:
            candidates.extend(home / ".dingo/components/dingo-mds-client" / version / program
                              for version in ("main", "latest"))
    else:
        candidates = [program]
    binary = next((str(candidate) for candidate in candidates if candidate
                   and os.path.isfile(candidate) and os.access(candidate, os.X_OK)), None)
    if not binary:
        raise ValueError("找不到可执行的 dingo-mds-client；请配置 MDS 客户端路径")
    addresses = req["mds_addr"].split(",")
    selected = None
    for address in addresses:
        try:
            host, port_text = address.rsplit(":", 1)
            if not host or not port_text.isdecimal():
                continue
            with socket.create_connection((host, int(port_text)), timeout=2):
                selected = address
                break
        except (OSError, ValueError):
            continue
    if selected is None:
        raise ValueError("MDS 地址均无法连接；未执行命令")
    return [binary] + ["--mds_addr=" + selected if arg.startswith("--mds_addr=") else arg
                       for arg in argv[1:]]


def run_mds_command(req, argv):
    """Resolve directory paths against MDS endpoints without replaying mutations."""
    action = req["action"]
    if action not in ("dirstat.info", "dirstat.summary", "dirstat.sync"):
        return run_command(prepare_mds_command(req, argv), require_json="--format" in argv)

    candidates = []
    for address in req["mds_addr"].split(","):
        try:
            candidates.append(prepare_mds_command({**req, "mds_addr": address}, argv))
        except ValueError as exc:
            if "MDS 地址均无法连接" not in str(exc):
                raise
    if not candidates:
        raise ValueError("MDS 地址均无法连接；未执行命令")

    last_error = None
    if action == "dirstat.sync":
        # The CLI's initial path Lookup uses only --mds_addr. Probe it with a
        # read before running the mutation once on a working endpoint.
        def probe_argv(command):
            return ["--cmd=info" if part == "--cmd=syncdirstat" else part
                    for part in command if part not in ("--recursive", "--repair")]
        for command in candidates:
            try:
                probe = run_command(probe_argv(command))
            except CommandFailure as exc:
                last_error = str(exc)
                continue
            if probe.get("stdout", "").strip():
                result = run_command(command)
                if not result.get("stdout", "").strip():
                    raise CommandFailure("目录统计同步未返回结果；请检查 MDS 客户端日志")
                return result
    else:
        for command in candidates:
            try:
                result = run_command(command)
            except CommandFailure as exc:
                last_error = str(exc)
                continue
            if result.get("stdout", "").strip():
                return result
    detail = "；最后错误：" + last_error[-4096:] if last_error else "；请检查路径及 MDS 客户端日志"
    raise CommandFailure("目录路径在所有可连接的 MDS 上均未返回统计结果" + detail)


def verify_mds_change(req, data):
    action = req["action"]
    if action not in ("trash.configure", "dirstat.enable"):
        return data
    fs_name = req["parameters"]["fs_name"]
    expected_key = "trash_days" if action == "trash.configure" else "enable_dir_stats"
    expected = req["parameters"]["trash_days"] if action == "trash.configure" else req["parameters"]["enable"]
    argv = ["dingo", "fs", "query", "--fsname", fs_name, "--mdsaddr", req["mds_addr"], "--format", "json"]
    for attempt in range(3):
        query = run_command(argv, require_json=True)
        info = query.get("result", {}).get("fs_info", {})
        if info.get(expected_key) == expected:
            return {**data, "verified": True, "effective_value": info[expected_key]}
        if attempt < 2:
            time.sleep(1)
    raise ValueError("命令已执行，但复查文件系统配置未得到预期值；请刷新查询确认")

def run_command(argv, timeout=45, require_json=False, *, max_stdout=MAX_OUTPUT):
    result = traced_popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    buffers = {result.stdout: bytearray(), result.stderr: bytearray()}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("command timed out")
                for key, _ in selector.select(min(0.2, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = buffers[key.fileobj]
                    limit = max_stdout if key.fileobj is result.stdout else MAX_OUTPUT
                    if len(buffer) + len(chunk) > limit:
                        raise ValueError("command output exceeded limit")
                    buffer.extend(chunk)
            result.wait(timeout=max(0.001, deadline - time.monotonic()))
    except BaseException as exc:
        try:
            os.killpg(result.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        result.wait()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise ValueError("command timed out") from None  # noqa: TRY004 - timeout domain error
        raise
    finally:
        result.stdout.close()
        result.stderr.close()
    stdout, stderr = bytes(buffers[result.stdout]), bytes(buffers[result.stderr])
    text, error_text = (
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )
    if result.returncode:
        # CLI can return structured MDS errors on stdout alongside stderr.
        detail = text[-4096:]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            try:
                check_json(parsed)
            except ValueError as exc:
                detail = str(exc)
        diagnostics = [detail] if detail else []
        if error_text:
            diagnostics.append("stderr: " + error_text[-4096:])
        raise CommandFailure(
            f"command failed (exit {result.returncode}): " + "; ".join(diagnostics)
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if require_json:
            raise ValueError("command returned invalid JSON") from None
        # Verbose fs query embeds the response in surrounding diagnostic text.
        data = None
        decoder = json.JSONDecoder()
        for match in list(re.finditer(r"\{", text))[:1000]:
            try:
                candidate, _ = decoder.raw_decode(text[match.start() :])
                if isinstance(candidate, dict):
                    check_json(candidate)
                    data = candidate
                    break
            except json.JSONDecodeError:
                continue
        if data is None:
            if re.search(r"(?im)^\s*(?:(?:error|fatal|failed|fail to|only root can restore)\b|[✗×])", text + "\n" + error_text):
                raise CommandFailure("command reported failure: " + (text + "\n" + error_text)[-4096:])
            return {"stdout": text, "stderr": error_text, "returncode": 0}
    try:
        return check_json(data)
    except ValueError as exc:
        raise CommandFailure(str(exc)) from exc


def open_directory(path, create=False, private=False):
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "\x00" in path
        or "//" in path
        or any(p in (".", "..") for p in path.split("/"))
    ):
        raise ValueError("invalid absolute directory")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    managed = False
    try:
        for part in path.split("/"):
            if not part:
                continue
            managed = managed or part.startswith("dingofs-platform-resources")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=fd,
            )
            os.close(fd)
            fd = nxt
            info = os.fstat(fd)
            if (
                private
                and managed
                and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)
            ):
                raise ValueError(
                    "resource directory must be owned by the execution user and private"
                )
        return fd
    except BaseException:
        os.close(fd)
        raise


class OwnedState:
    def __init__(self, path, identity, create=False):
        self.fd = None
        self.lock_fd = None
        parent, name = os.path.split(path.rstrip("/"))
        parent_fd = open_directory(parent, create=create, private=True)
        created = False
        try:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent_fd)
                    created = True
                except FileExistsError:
                    pass
            self.fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            info = os.fstat(self.fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("resource directory ownership or permissions mismatch")
            if created:
                owner = os.open(
                    "owner.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=self.fd,
                )
                with os.fdopen(owner, "w") as stream:
                    json.dump({"identity": identity}, stream)
            try:
                owner = self.read("owner.json")
            except FileNotFoundError:
                raise ValueError(
                    "existing directory has no platform ownership record"
                ) from None
            if owner != {"identity": identity}:
                raise ValueError("resource ownership record mismatch")
            self.lock_fd = os.open(
                "lock",
                os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.fd,
            )
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent_fd)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        for name in ("lock_fd", "fd"):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def read(self, name="state.json"):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        with os.fdopen(fd) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("invalid resource state file")
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("resource state exceeded limit")
            return json.loads(raw)

    def load(self):
        try:
            return self.read()
        except FileNotFoundError:
            return {}

    def save(self, state):
        name = "state-" + uuid.uuid4().hex + ".tmp"
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=self.fd,
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, "state.json", src_dir_fd=self.fd, dst_dir_fd=self.fd)


def process_identity(pid):
    try:
        root = Path("/proc") / str(pid)
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {
            "pid": int(pid),
            "start_ticks": fields[19],
            "exe": os.readlink(root / "exe"),
            "argv": (root / "cmdline")
            .read_bytes()
            .decode()
            .rstrip("\x00")
            .split("\x00"),
        }
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def same_process(expected, actual):
    return bool(
        expected
        and actual
        and all(
            expected.get(k) == actual.get(k)
            for k in ("pid", "start_ticks", "exe", "argv")
        )
    )


def process_flags(argv):
    result = {}
    index = 1
    while index < len(argv):
        value = argv[index]
        if value.startswith("--"):
            if "=" in value:
                key, value = value[2:].split("=", 1)
            else:
                key = value[2:]
                value = (
                    argv[index + 1]
                    if index + 1 < len(argv) and not argv[index + 1].startswith("--")
                    else "true"
                )
                if value != "true":
                    index += 1
            if key in result:
                raise ValueError("duplicate process flag")
            result[key] = value
        index += 1
    return result


class MultipleResourceProcesses(ValueError):
    """Process ownership is ambiguous, including during daemon startup."""


def find_process(req, *, exclude_pid=None):
    record = req["record"]
    cache = req["action"].startswith("cache.")
    matches = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        if exclude_pid is not None and int(entry.name) == exclude_pid:
            continue
        process = process_identity(int(entry.name))
        if not process or os.path.basename(process["exe"]) != (
            "dingo-cache" if cache else "dingo-client"
        ):
            continue
        flags = process_flags(process["argv"])
        if flags.get("log_dir") != record["log_dir"]:
            continue
        if cache:
            match = (
                flags.get("id") == record["member_id"]
                and flags.get("group_name") == record["group_name"]
            )
        else:
            match = record["mount_path"] in process["argv"]
        if match:
            matches.append(process)
    if len(matches) > 1:
        raise MultipleResourceProcesses("multiple processes match this resource")
    return matches[0] if matches else None


def _stop_process_compat(expected, timeout, sig=signal.SIGTERM):
    # Older remote Python/kernel versions lack pidfd. Revalidate immediately
    # before the single SIGTERM; never retry the signal or signal by port/name.
    # Unlike pidfd this cannot atomically eliminate the check-to-kill PID race.
    current = process_identity(expected["pid"])
    if current is None:
        return False
    if not same_process(expected, current):
        raise ValueError("recorded process identity changed; refusing signal")
    try:
        traced_signal(expected, "os.kill", lambda: os.kill(expected["pid"], sig), sig)
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + timeout
    while True:
        current = process_identity(expected["pid"])
        if current is None or not same_process(expected, current):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("process did not stop after {}; check member process logs (pid={})".format(signal.Signals(sig).name, expected["pid"]))
        time.sleep(min(0.2, remaining))


def stop_recorded_process(expected, timeout=30, *, force=False):
    sig = signal.SIGKILL if force else signal.SIGTERM
    if not expected or type(expected.get("pid")) is not int or expected["pid"] <= 1:
        raise ValueError("missing recorded process identity")
    current = process_identity(expected["pid"])
    if current is None:
        return False
    if not same_process(expected, current):
        raise ValueError("recorded process identity changed; refusing signal")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return _stop_process_compat(expected, timeout, sig)
    try:
        fd = os.pidfd_open(expected["pid"])
    except ProcessLookupError:
        return False
    except OSError as exc:
        if exc.errno == errno.ENOSYS:
            return _stop_process_compat(expected, timeout, sig)
        raise
    try:
        current = process_identity(expected["pid"])
        if current is None:
            return False
        if not same_process(expected, current):
            raise ValueError("recorded process identity changed; refusing signal")
        try:
            traced_signal(expected, "pidfd_send_signal", lambda: signal.pidfd_send_signal(fd, sig), sig)
        except ProcessLookupError:
            return False
        except OSError as exc:
            if exc.errno == errno.ENOSYS:
                return _stop_process_compat(expected, timeout, sig)
            raise
        if not select.select([fd], [], [], timeout)[0]:
            raise ValueError("process did not stop after {}; check member process logs (pid={})".format(signal.Signals(sig).name, expected["pid"]))
        return True
    finally:
        os.close(fd)


def rdma_flags(record):
    flags = ["--use_rdma=" + str(record.get("use_rdma", False)).lower()]
    if record.get("use_rdma"):
        flags.extend(
            [
                "--cache_rdma_device=" + record["rdma_device"],
                "--cache_rdma_port_num=" + str(record["rdma_port"]),
            ]
        )
    return flags


def mount_argv(req):
    r = req["record"]
    argv = [
        "dingo",
        "fs",
        "mount",
        "--allow_other",
        "mds://" + req["mds_addr"] + "/" + r["fs_name"],
        r["mount_path"],
        "--log_dir=" + r["log_dir"],
        "--daemonize=true",
        *rdma_flags(r),
    ]
    extra = r.get("mount_options", {})
    protected = {"conf", "daemonize", "log_dir", "cache_dir_uuid", "fuse_subdir", "cache_group", "use_rdma", "cache_rdma_device", "cache_rdma_port_num"}
    if set(extra) & protected:
        raise ValueError("mount options must not override platform-managed fields")
    argv.extend("--{}={}".format(key, value) for key, value in extra.items())
    if r.get("subdir"):
        argv.append("--fuse_subdir=" + r["subdir"])
    if r.get("cache_group"):
        argv.append("--cache_group=" + r["cache_group"])
    return argv


def cache_argv(req):
    r = req["record"]
    values = {
        "id": r["member_id"],
        "group_name": r["group_name"],
        "listen_ip": r["listen_ip"],
        "listen_port": r["listen_port"],
        "mds_addrs": req["mds_addr"],
        "cache_dir": r["cache_dir"],
        "cache_size_mb": r["cache_size_mb"],
        "log_dir": r["log_dir"],
        "daemonize": "true",
    }
    extra = r.get("cache_options", {})
    protected = set(values) | {"conf", "cache_dir_uuid", "use_rdma", "cache_rdma_device", "cache_rdma_port_num"}
    if set(extra) & (protected - {"cache_expire_s"}):
        raise ValueError("cache options must not override managed member arguments")
    values.update(extra)
    return [
        "dingo",
        "cache",
        "start",
        *["--{}={}".format(*item) for item in values.items()],
        *rdma_flags(r),
    ]


def mount_identity(path):
    # Persist the kernel mount identity so old records cannot unmount a later
    # replacement at the same pathname after a lazy unmount.
    with open("/proc/self/mountinfo") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) < 10 or "-" not in fields:
                continue
            mount_path = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
            if mount_path == path:
                separator = fields.index("-")
                return {
                    "mount_id": fields[0],
                    "device": fields[2],
                    "root": fields[3],
                    "mount_path": mount_path,
                    "fs_type": fields[separator + 1],
                    "source": fields[separator + 2],
                }
    return None


def mounted(path):
    return mount_identity(path) is not None


def require_owned_mount(state, path):
    actual = mount_identity(path)
    if actual is not None and actual != state.get("mount"):
        raise ValueError(
            "mount identity changed; refusing to operate on a replacement mount"
        )
    return actual


def read_logs(req, *, max_bytes=MAX_OUTPUT):
    r, p = req["record"], req["parameters"]
    root = open_directory(r["log_dir"])
    try:
        name = p.get("filename", "")
        if not name:
            rows = []
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1000:
                        break
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        rows.append(
                            {
                                "name": entry.name,
                                "size": info.st_size,
                                "mtime": info.st_mtime,
                            }
                        )
            return {
                "files": sorted(rows, key=lambda item: (-item["mtime"], item["name"])),
                "truncated": index >= 1000 if "index" in locals() else False,
            }
        if (
            not isinstance(name, str)
            or name in (".", "..")
            or "/" in name
            or "\x00" in name
        ):
            raise ValueError("invalid log filename")
        lines = p.get("lines", 500)
        if type(lines) is not int or not 1 <= lines <= 1000:
            raise ValueError("invalid log line limit")
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=root,
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("log is not a regular file")
            raw = os.pread(
                fd, min(info.st_size, max_bytes), max(0, info.st_size - max_bytes)
            )
            chunks = raw.splitlines(keepends=True)
            text = b"".join(chunks[-lines:]).decode("utf-8", "replace")
            text = re.sub(
                r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", text
            )
            text = "".join(
                c
                for c in text
                if c in "\n\r\t" or ord(c) >= 32 and not 127 <= ord(c) <= 159
            )
            return {
                "filename": name,
                "text": text,
                "truncated": info.st_size > max_bytes or len(chunks) > lines,
            }
        finally:
            os.close(fd)
    finally:
        os.close(root)


def failure_logs(req):
    """Best-effort bounded tails; never follow log symlinks or mask the failure."""
    details = {"log_dir": (req.get("record") or {}).get("log_dir", ""), "files": []}
    try:
        listing = read_logs({**req, "parameters": {}})
        def priority(row):
            name = row["name"].lower()
            rank = 0 if name == "launcher.log" else 1 if "fatal" in name else 2 if "error" in name or "stderr" in name else 3 if "stdout" in name else 4
            return rank, -row["mtime"], name
        rows = sorted(listing["files"], key=priority)
        details["truncated"] = listing.get("truncated", False) or len(rows) > 6
        for row in rows[:6]:
            try:
                details["files"].append(read_logs({**req, "parameters": {"filename": row["name"], "lines": 80}}, max_bytes=16384))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                details["files"].append({"filename": row["name"], "error": str(exc)})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        details["error"] = str(exc)
    return details


def _launch(req, argv):
    log_fd = open_directory(req["record"]["log_dir"], create=True, private=True)
    try:
        fd = os.open(
            "launcher.log",
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=log_fd,
        )
        with os.fdopen(fd, "ab") as log:
            # Do not let daemonized processes retain SSH stdout/stderr pipes.
            return traced_popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
    finally:
        os.close(log_fd)


def member_list(req, timeout=15):
    result = run_command(
        [
            "dingo",
            "cache",
            "member",
            "list",
            "--mdsaddr",
            req["mds_addr"],
            "--format",
            "json",
        ],
        timeout=timeout,
        require_json=True,
    )
    body = result.get("result")
    if not isinstance(body, dict):
        raise ValueError("invalid cache member list: missing result object")
    if "members" not in body and (not isinstance(result.get("error"), dict) or result["error"].get("code") != 0):
        raise ValueError("invalid cache member list: missing successful member response")
    # Protobuf JSON omits empty repeated fields.
    members = body.get("members", [])
    if not isinstance(members, list) or any(
        not isinstance(member, dict) or not member.get("member_id")
        for member in members
    ):
        raise ValueError("invalid cache member list")
    return members


def manage_member(req):
    p = req["parameters"]
    matches = [row for row in member_list(req) if row["member_id"] == p["member_id"]]
    if len(matches) != 1:
        raise CommandFailure("成员不存在或 UUID 重复，请刷新列表")
    row = matches[0]
    group = row.get("group_name") or ""
    if group != p.get("group_name", ""):
        raise CommandFailure("成员所属缓存组已变化，请刷新列表后重新操作")
    verb = {"cache.leave": "leave", "cache.unlock": "unlock", "cache.weight": "set"}[req["action"]]
    argv = ["dingo", "cache", "member", verb, "--memberid", p["member_id"],
            "--ip", row["ip"], "--port", str(row["port"]), "--mdsaddr", req["mds_addr"], "--format", "json"]
    if verb == "leave":
        if not group:
            raise CommandFailure("该成员已经未分组，无需离组")
        argv += ["--group", group]
    if verb == "set":
        argv += ["--weight", str(p["weight"])]
    else:
        argv += ["--noconfirm"]
    response = run_command(argv, require_json=True)
    return "succeeded", {"member_id": p["member_id"], "response": response}


def delete_member_registration(req):
    """Remove exactly one offline registration, without owning its process."""
    member_id = req["parameters"]["member_id"]
    matches = [m for m in member_list(req) if m["member_id"] == member_id]
    if not matches:
        raise CommandFailure("缓存成员已不存在，请刷新缓存成员列表")
    if len(matches) != 1:
        raise CommandFailure("缓存成员 ID 重复，无法确定删除目标")
    member = matches[0]
    state = member.get("state")
    if type(state) not in (int, str) or state not in (
        0, 3, "0", "3", "CacheGroupMemberStateUnknown", "CacheGroupMemberStateOffline",
    ):
        raise CommandFailure("缓存成员尚未离线或状态不允许删除，请先停止对应缓存进程，等待成员离线后刷新列表")
    response = run_command(
        ["dingo", "cache", "member", "delete", member_id,
         "--mdsaddr", req["mds_addr"], "--noconfirm", "--format", "json"],
        timeout=15,
        require_json=True,
    )
    return "deleted", {
        "member_id": member_id,
        "group_name": member.get("group_name"),
        "ip": member.get("ip"),
        "port": member.get("port"),
        "cache_data_retained": True,
        "response": response,
    }


def port_busy(port):
    # dingo-cache binds all interfaces by default, so check wildcard sockets.
    for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind((address, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return True
            if family == socket.AF_INET6 and exc.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            raise ValueError("无法检查端口 {}：{}".format(port, exc)) from None
    return False


def select_mount_port(req):
    """Choose a free client dummy-server port on the mount target host."""
    options = req["record"].get("mount_options", {})
    preferred = int(options.get("vfs_dummy_server_port", 10000))
    if not 1 <= preferred <= 65535:
        raise ValueError("vfs_dummy_server_port must be in [1, 65535]")
    if not port_busy(preferred):
        return preferred
    for candidate in range(10000, 20000):
        if not port_busy(candidate):
            return candidate
    raise ValueError("客户端自动端口范围 10000–19999 已无可用端口")


def select_cache_port(req):
    r = req["record"]
    # Verify the advertised address belongs to this host before selecting a port.
    try:
        family = socket.AF_INET6 if ":" in r["listen_ip"] else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((r["listen_ip"], 0))
    except OSError as exc:
        raise ValueError("监听 IP 不可用于当前机器：{}".format(exc)) from None
    current_members = member_list(req)
    if any(m["member_id"] == r["member_id"] for m in current_members):
        raise ValueError("成员 ID 已在 MDS 注册，请使用其他 ID")
    registered = {int(m.get("port", 0)) for m in current_members
                  if m["member_id"] != r["member_id"] and m.get("ip") == r["listen_ip"]}
    reserved = set(r.get("reserved_ports", []))
    def reason(port):
        if port in reserved:
            return "已被平台其他成员或任务预留"
        if port in registered:
            return "已被 MDS 中的其他成员登记"
        if port_busy(port):
            return "已被目标机器上的进程占用"
        return ""
    preferred = r["listen_port"]
    if not reason(preferred):
        return preferred
    candidate = next((port for port in range(21000, 30000) if not reason(port)), None)
    if r.get("port_mode", "manual") == "manual":
        raise ValueError("端口 {} {}；{}".format(preferred, reason(preferred),
            "建议使用端口 {} 或自动分配".format(candidate) if candidate else "自动范围内暂无可用端口"))
    if candidate is None:
        raise ValueError("自动端口范围 21000–29999 已无可用端口")
    return candidate


def check_group_available(req):
    # A group can contain members created by multiple requests or tools.
    # Stop/delete ownership is enforced by _membership and recorded process identity.
    if req.get("action") != "cache.create":
        return
    record = req["record"]
    for member in member_list(req):
        if member["member_id"] == record["member_id"]:
            raise ValueError("成员 ID 已在 MDS 注册，请使用其他 ID")
        if (member["member_id"] != record["member_id"]
                and member.get("ip") == record["listen_ip"]
                and int(member.get("port", 0)) == record["listen_port"]):
            raise ValueError("cache member endpoint is already registered by another member; choose a different listen port")


def _membership(req):
    members = member_list(req)
    r = req["record"]
    matches = [m for m in members if m.get("member_id") == r["member_id"]]
    if len(matches) > 1:
        raise ValueError("duplicate cache member identity")
    if matches:
        row = matches[0]
        if (
            row.get("ip") != r["listen_ip"]
            or int(row.get("port", 0)) != r["listen_port"]
            or row.get("group_name", "") not in ("", r["group_name"])
        ):
            raise ValueError("cache member ownership changed")
        return row
    return None


def _leave(req):
    row = _membership(req)
    if row and row.get("group_name"):
        r = req["record"]
        run_command(
            [
                "dingo",
                "cache",
                "member",
                "leave",
                "--group",
                r["group_name"],
                "--memberid",
                r["member_id"],
                "--ip",
                r["listen_ip"],
                "--port",
                str(r["listen_port"]),
                "--mdsaddr",
                req["mds_addr"],
                "--noconfirm",
                "--format",
                "json",
            ],
            require_json=True,
        )


def verify_external_members(req):
    rows = member_list(req)
    for expected in req["record"]["members"]:
        matches = [row for row in rows if row["member_id"] == expected["member_id"]]
        if len(matches) != 1:
            raise ValueError("成员登记已变化，请刷新列表：" + expected["member_id"])
        row = matches[0]
        if (row.get("group_name", "") != expected["group_name"] or
                row.get("ip") != expected["listen_ip"] or int(row.get("port", 0)) != expected["listen_port"]):
            raise ValueError("成员组名或地址已变化，未执行停止，请刷新列表：" + expected["member_id"])
    return "verified", {"member_ids": req["parameters"]["member_ids"]}


def verify_cache_host(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((address, 0))
    except OSError as exc:
        raise ValueError("成员 IP 不属于当前执行机器，请更新机器资源映射：" + address) from exc


def stop_external_member(req):
    # The controller resolved this record from the MDS query and an authorized
    # machine; no caller supplies a PID, command, or executable path.
    if os.geteuid() != 0:
        raise ValueError("停止外部成员需切换为 root，以核验所有缓存进程；请完成 sudo 认证")
    record = req["record"]
    verify_cache_host(record["listen_ip"])
    matches = []
    # A verified registration can outlive MDS scale-down. Require every
    # current endpoint in the startup list, while allowing retired endpoints.
    expected_mds = {address.strip() for address in req["mds_addr"].split(",") if address.strip()}
    if not expected_mds:
        raise ValueError("缺少当前集群 MDS 地址，未发送停止信号")
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        process = process_identity(int(entry.name))
        if not process or os.path.basename(process["exe"]) != "dingo-cache":
            continue
        flags = process_flags(process["argv"])
        if flags.get("id") != record["member_id"]:
            continue
        if (flags.get("group_name") != record["group_name"] or
                flags.get("listen_ip") != record["listen_ip"] or
                flags.get("listen_port") != str(record["listen_port"]) or
                not expected_mds.issubset({address.strip() for address in flags.get("mds_addrs", "").split(",") if address.strip()})):
            raise ValueError("发现同 UUID 进程，但组名、监听地址或 MDS 参数不一致，未发送停止信号：" + record["member_id"])
        matches.append(process)
    if len(matches) > 1:
        raise ValueError("多个进程匹配成员 UUID，无法唯一确定停止目标：" + record["member_id"])
    if not matches:
        if port_busy(record["listen_port"]):
            raise ValueError("成员端口仍被占用，但未找到可核验的 dingo-cache 进程；请检查启动参数或进程权限")
        return "stopped", {"member_id": record["member_id"], "already_absent": True}
    stop_recorded_process(matches[0], **({"force": True} if record.get("force_stop") else {}))
    return "stopped", {"member_id": record["member_id"], "pid": matches[0]["pid"], "external": True, "process_stopped": True}


def wait_members_offline(req):
    ids = req["parameters"]["member_ids"]
    deadline = time.monotonic() + 180
    remaining = list(ids)
    while time.monotonic() < deadline:
        rows = member_list(req, timeout=max(0.01, min(15, deadline - time.monotonic())))
        indexed = {}
        for row in rows:
            indexed.setdefault(row["member_id"], []).append(row)
        remaining = [mid for mid in ids if mid in indexed and
                     (len(indexed[mid]) != 1 or indexed[mid][0].get("state") not in
                      (3, "3", "CacheGroupMemberStateOffline"))]
        if not remaining:
            return "stopped", {"member_ids": ids, "offline_confirmed": True}
        time.sleep(min(3, max(0, deadline - time.monotonic())))
    raise ValueError("等待成员离线超时（180 秒），请刷新核实，未确认离线：" + ", ".join(remaining))


def hot_remount(req, store, state, old_process):
    """Relaunch the same mount without unmounting; DingoFS hands off its FUSE fd."""
    record = req["record"]
    if not same_process(old_process, process_identity(old_process["pid"])):
        raise ValueError("recorded client process changed before hot update")
    original_mount = require_owned_mount(state, record["mount_path"])
    if not original_mount:
        raise ValueError("client is no longer mounted; refresh its status")
    port = state.get("vfs_dummy_server_port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("actual client port is unknown; refresh its status before hot update")
    record["mount_options"] = {**record.get("mount_options", {}),
                               "vfs_dummy_server_port": str(port)}
    launched = _launch(req, mount_argv(req))
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        # During handoff both processes can briefly exist. Ignore only the
        # verified old PID; any second new candidate remains an error.
        successor = find_process(req, exclude_pid=old_process["pid"])
        if successor and require_owned_mount(state, record["mount_path"]):
            state.update(process=successor, state="mounted")
            store.save(state)
            return "mounted", {"mount_path": record["mount_path"],
                               "vfs_dummy_server_port": port, "hot_updated": True}
        if launched.poll() not in (None, 0):
            raise ValueError("client hot update launcher failed; inspect launcher.log")
        time.sleep(0.5)
    raise ValueError("client hot update did not complete; original ownership retained")


def lifecycle(req):
    action, r = req["action"], req["record"]
    identity = req["resource_id"] + ":" + r.get("member_id", "mount")
    if action == "mount.logs":
        return "ready", read_logs(req)
    creating = action in ("cache.create", "mount.create", "mount.remount")
    mount_start = action in ("mount.create", "mount.remount")
    if action in ("cache.stop", "cache.delete"):
        check_group_available(req)
    try:
        owned_state = OwnedState(r["state_dir"], identity, create=action in ("cache.create", "mount.create"))
    except FileNotFoundError:
        if action in ("cache.stop", "cache.delete"):
            if find_process(req) is None and _membership(req) is None:
                return "deleted" if action == "cache.delete" else "stopped", {
                    "member_id": r["member_id"],
                    "already_absent": True,
                }
            raise ValueError(
                "cache ownership state is missing for an existing member"
            ) from None
        raise
    with owned_state as store:
        state = store.load()
        if action.startswith("cache.") and "listen_port" in state:
            r["listen_port"] = state["listen_port"]
        process = state.get("process")
        current = process_identity(process["pid"]) if process else None
        if action == "mount.remount":
            if require_owned_mount(state, r["mount_path"]):
                if not same_process(process, current):
                    raise ValueError("cannot verify the process owning this mount")
                return hot_remount(req, store, state, process)
            if current and same_process(process, current):
                raise ValueError("previous client process is still running; retry after it exits")
            # The prior process may have exited and its PID may have been reused.
            # Keep the owner identity and logs, then begin a fresh launch.
            state = {"state": "unmounted"}
            store.save(state)
            current = None
        if current and not same_process(process, current):
            raise ValueError("recorded process identity changed")
        if action == "mount.status":
            active = require_owned_mount(state, r["mount_path"]) is not None
            return (
                "mounted"
                if active and current
                else "unmounted"
                if not active
                else "unknown",
                {"mounted": active, "process_running": bool(current),
                 "vfs_dummy_server_port": state.get("vfs_dummy_server_port")},
            )
        if creating:
            if current:
                if mount_start and require_owned_mount(
                    state, r["mount_path"]
                ):
                    return "mounted", {"already_running": True,
                                       "vfs_dummy_server_port": state.get("vfs_dummy_server_port")}
                if action == "cache.create":
                    member = _membership(req)
                    if (
                        member
                        and member.get("group_name") == r["group_name"]
                        and member.get("state")
                        in (1, "1", "CacheGroupMemberStateOnline")
                    ):
                        return "running", {"already_running": True, "member": member}
                raise ValueError("owned process exists but resource is not ready")
            target = r["cache_dir"] if action == "cache.create" else r["mount_path"]
            if mounted(target):
                raise ValueError("target directory is already mounted")
            # Recover a process that was started before an interrupted SSH reply.
            recovered = find_process(req) if state.get("launch_started") else None
            if not recovered:
                if action == "cache.create" and not state.get("launch_started"):
                    r["listen_port"] = select_cache_port(req)
                    state["listen_port"] = r["listen_port"]
                    store.save(state)
                if mount_start and not state.get("launch_started"):
                    port = select_mount_port(req)
                    r["mount_options"] = {**r.get("mount_options", {}),
                                          "vfs_dummy_server_port": str(port)}
                    state["vfs_dummy_server_port"] = port
                    store.save(state)
                target_fd = open_directory(target, create=True)
                try:
                    if not state.get("launch_started"):
                        with os.scandir(target_fd) as entries:
                            if next(entries, None) is not None:
                                raise ValueError(
                                    "target directory must be empty for a new resource"
                                )
                finally:
                    os.close(target_fd)
                state.update(launch_started=True, state="starting")
                store.save(state)
                launched = _launch(
                    req,
                    cache_argv(req) if action == "cache.create" else mount_argv(req),
                )
            else:
                launched = None
            deadline = time.monotonic() + 45
            ambiguous = None
            while time.monotonic() < deadline:
                try:
                    process = recovered or find_process(req)
                    ambiguous = None
                except MultipleResourceProcesses as exc:
                    # Daemon parent and child can briefly share the same argv.
                    # Never pick either arbitrarily or relaunch; wait for one owner.
                    process = None
                    ambiguous = exc
                recovered = None
                if process:
                    state.update(process=process)
                    store.save(state)
                    if mount_start and mounted(r["mount_path"]):
                        state["state"] = "mounted"
                        state["mount"] = mount_identity(r["mount_path"])
                        store.save(state)
                        return "mounted", {"mount_path": r["mount_path"],
                                           "vfs_dummy_server_port": state.get("vfs_dummy_server_port")}
                    if action == "cache.create":
                        member = _membership(req)
                        if (
                            member
                            and member.get("group_name") == r["group_name"]
                            and member.get("state")
                            in (1, "1", "CacheGroupMemberStateOnline")
                        ):
                            state["state"] = "running"
                            store.save(state)
                            return "running", {"member": member}
                if launched and launched.poll() not in (None, 0):
                    state["launch_failed"] = True
                    store.save(state)
                    raise ValueError("resource launcher failed; inspect launcher.log")
                time.sleep(0.5)
            if ambiguous:
                raise ambiguous
            raise ValueError(
                "resource did not become ready; recorded state retained for retry"
            )
        if action == "mount.delete":
            if mounted(r["mount_path"]) or current:
                raise ValueError("client is still mounted or running; cannot delete its record")
            return "deleted", {"mount_path": r["mount_path"], "data_preserved": True}
        if action == "mount.unmount":
            if not require_owned_mount(state, r["mount_path"]):
                state["state"] = "unmounted"
                store.save(state)
                return "unmounted", {"process_running": bool(current)}
            if not current:
                raise ValueError("cannot verify the process owning this mount")
            # Preserve a pinned mountpoint descriptor and process identity until
            # the fixed unmount command finishes; never kill a mount by grep.
            fd = open_directory(r["mount_path"])
            try:
                if not same_process(process, process_identity(process["pid"])):
                    raise ValueError("mount process identity changed")
                require_owned_mount(state, r["mount_path"])
                run_command(
                    ["dingo", "fs", "umount", "-l", r["mount_path"]], timeout=30
                )
            finally:
                os.close(fd)
            if mounted(r["mount_path"]):
                raise ValueError("mount remains active after unmount")
            state["state"] = "unmounted"
            store.save(state)
            return "unmounted", {
                "process_running": bool(process_identity(process["pid"]))
            }
        if action in ("cache.stop", "cache.delete"):
            if not process and state.get("launch_started"):
                process = find_process(req)
                if process is None:
                    if not state.get("launch_failed"):
                        raise ValueError(
                            "startup ownership is not yet verifiable; retry after the launcher settles"
                        )
                else:
                    state["process"] = process
                    store.save(state)
                    current = process_identity(process["pid"])
                    if not same_process(process, current):
                        raise ValueError("recovered process identity changed")
            # A matched registration can be detached even when the recorded
            # process has already exited. The member ID/address remain checked.
            if action == "cache.delete":
                _leave(req)
            else:
                # Validate the UUID/address but retain group membership on stop.
                _membership(req)
            if current:
                stop_recorded_process(process, **({"force": True} if r.get("force_stop") else {}))
            state["state"] = "stopped"
            store.save(state)
            if action == "cache.stop":
                check_group_available(req)
                return "stopped", {"member_id": r["member_id"], "pid": process["pid"] if process else None, "process_stopped": True}
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                member = _membership(req)
                if member is None:
                    check_group_available(req)
                    state["state"] = "deleted"
                    store.save(state)
                    return "deleted", {
                        "member_id": r["member_id"],
                        "cache_data_retained": True,
                    }
                if member.get("state") in (
                    0,
                    3,
                    "0",
                    "3",
                    "CacheGroupMemberStateUnknown",
                    "CacheGroupMemberStateOffline",
                ):
                    run_command(
                        [
                            "dingo",
                            "cache",
                            "member",
                            "delete",
                            r["member_id"],
                            "--mdsaddr",
                            req["mds_addr"],
                            "--noconfirm",
                            "--format",
                            "json",
                        ],
                        timeout=15,
                        require_json=True,
                    )
                time.sleep(1)
            raise ValueError(
                "process stopped, but member is not yet deletable; retry deletion after the MDS offline timeout"
            )
    raise ValueError("unsupported lifecycle action")


def main(req):
    global TRACE_ENABLED
    COMMAND_TRACE.clear()
    TRACE_ENABLED = True
    secrets = [
        req.get("parameters", {}).get(key, "")
        for key in ("s3_ak", "s3_sk", "rados_key")
    ]
    try:
        if req.get("commands"):
            options = {"max_stdout": FS_LIST_MAX_OUTPUT} if req["action"] == "fs.list" else {}
            values = [
                run_mds_command(req, argv) if req["action"].startswith(("trash.", "dirstat."))
                and req["action"] != "trash.get" else
                run_command(argv, require_json="--format" in argv, **options)
                for argv in req["commands"]
            ]
            data = (
                {"groups": values[0], "members": values[1]}
                if req["action"] == "cache.list"
                else values[0]
            )
            data = verify_mds_change(req, data)
            state = "succeeded"
        elif req["action"] in ("cache.leave", "cache.unlock", "cache.weight"):
            state, data = manage_member(req)
        elif req["action"] == "cache.verify_members":
            state, data = verify_external_members(req)
        elif req["action"] == "cache.stop_external":
            state, data = stop_external_member(req)
        elif req["action"] == "cache.wait_offline":
            state, data = wait_members_offline(req)
        elif req["action"] == "cache.plan":
            port = select_cache_port(req)
            state, data = "planned", {"effective_port": port, "member": {
                key: value for key, value in req["record"].items() if key != "reserved_ports"
            }}
            data["member"]["listen_port"] = port
        elif req["action"] == "cache.delete" and "member_id" in req.get("parameters", {}):
            state, data = delete_member_registration(req)
        else:
            state, data = lifecycle(req)
        if req["action"] == "cache.create":
            data = {**data, "effective_port": req["record"]["listen_port"], "planned_port": req["record"].get("planned_port", req["record"]["listen_port"])}
        if TRACE_ENABLED:
            data = {**data, "executed_commands": list(COMMAND_TRACE)}
        print(
            json.dumps(
                redact(
                    {
                        "state": state,
                        "returncode": 0,
                        "data": data,
                        "resource_id": req["resource_id"],
                    },
                    secrets,
                    show_storage_keys=req["action"] == "fs.get",
                ),
                ensure_ascii=True,
                separators=(",", ":") if req["action"] == "fs.list" else None,
            ),
            flush=True,
        )
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                redact(
                    {
                        "state": "failed",
                        "returncode": 1,
                        "error": "resource_operation_failed",
                        "command_completed": isinstance(exc, CommandFailure),
                        "message": str(exc),
                        **({"executed_commands": list(COMMAND_TRACE)} if TRACE_ENABLED else {}),
                        **({"effective_port": req["record"]["listen_port"]} if req.get("action") == "cache.create" and "listen_port" in req.get("record", {}) else {}),
                        "resource_id": req.get("resource_id"),
                        **({"diagnostics": failure_logs(req)} if req.get("action") in ("cache.create", "mount.create") else {}),
                    },
                    secrets,
                ),
                ensure_ascii=True,
            ),
            flush=True,
        )
        return 1
    finally:
        TRACE_ENABLED = False


if __name__ == "__main__":
    sys.exit(main(json.loads(sys.argv[1])))
