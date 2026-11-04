"""Operate discovered clients; keep original launch arguments only on their host."""
import json
import os
import pwd
import subprocess
import time
import uuid
from pathlib import Path


def capture_external_mounts(req, data, helper):
    """Capture restart settings on the target before a later manual unmount."""
    cluster_id = req["record"]["cluster_id"]
    external_ids = req["record"].get("external_mounts", [])
    for row in data["mounts"]:
        if row.get("cluster_match") != "current" or not row.get("identity"):
            continue
        saved_id = row.get("saved_resource_id")
        if saved_id and saved_id not in external_ids:
            continue
        rid = saved_id or str(uuid.uuid4())
        record = dict(row, client_user=row["client_user"],
                      state_dir=f"/tmp/dingofs-platform-resources-root/{cluster_id}/{rid}")
        try:
            mount, process = _external_verified({**req, "record": record}, helper, row["identity"])
            if not process:
                raise ValueError("客户端已退出，请重新扫描")
            launch = _external_capture(process, record)
            state = dict(identity=row["identity"], scan_identity=row["identity"],
                         process=process, mount=mount, launch=launch, state="mounted")
            if len(json.dumps(state).encode()) > 65536:
                raise ValueError("客户端启动参数过大")
            with helper.OwnedState(record["state_dir"], rid + ":external-mount", create=True) as store:
                store.save(state)
            row["adopted_resource_id"] = rid
        except (ValueError, OSError, KeyError) as exc:
            row["adoption_error"] = str(exc)
            row["reason"] = "保存客户端管理信息失败：" + str(exc)
    return data


def _external_verified(req, helper, expected):
    record = req["record"]
    mount = helper.mount_identity(record["mount_path"])
    if mount is None:
        return None, None
    process = helper.process_identity(expected.get("pid"))
    if (not process or mount["mount_id"] != expected.get("mount_id")
            or mount["fs_type"] != "fuse.dingofs"
            or any(process.get(k) != expected.get(k) for k in ("pid", "start_ticks", "exe"))
            or os.readlink("/proc/self/ns/mnt") != expected.get("namespace")
            or os.readlink(f'/proc/{process["pid"]}/ns/mnt') != expected.get("namespace")):
        raise ValueError("挂载或客户端进程已变化，请重新扫描已有挂载后再操作")
    parsed = helper._scan_client(process["argv"])
    if (not parsed or parsed[0] != record["mount_path"] or parsed[1] != record["fs_name"]
            or parsed[2] != helper._scan_endpoints(req["mds_addr"])):
        raise ValueError("客户端所属集群或文件系统已变化，请重新扫描")
    return mount, process


def _external_capture(process, record):
    root = Path("/proc") / str(process["pid"])
    uid = root.stat().st_uid
    account = pwd.getpwuid(uid)
    if account.pw_name != record["client_user"]:
        raise ValueError("客户端运行用户已变化，请重新扫描")
    # Preserve runtime library lookup without moving credentials to the API/DB.
    with open(root / "environ", "rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("客户端环境过大，无法保存重新挂载参数")
    env = {}
    for entry in raw.split(b"\0"):
        key, sep, value = entry.partition(b"=")
        if sep and key in (b"PATH", b"LD_LIBRARY_PATH"):
            env[key.decode()] = value.decode()
    return dict(argv=[process["exe"], *process["argv"][1:]], user=account.pw_name,
                cwd=os.readlink(root / "cwd"), env=env)


def _external_launch(req, helper, launch):
    if not launch or not launch.get("argv"):
        raise ValueError("没有保存的原始启动参数，请重新扫描正在运行的客户端")
    argv = launch["argv"]
    if not os.path.isabs(argv[0]) or not os.access(argv[0], os.X_OK):
        raise ValueError("原客户端程序不存在或不可执行，请恢复该程序后重试")
    account = pwd.getpwnam(launch["user"])
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", **launch.get("env", {}), "HOME": account.pw_dir,
           "USER": account.pw_name, "LOGNAME": account.pw_name}
    runuser = next((p for p in ("/usr/sbin/runuser", "/sbin/runuser") if os.access(p, os.X_OK)), None)
    if not runuser:
        raise ValueError("目标机器缺少 runuser，无法以原用户启动客户端")
    log_fd = helper.open_directory(req["record"]["state_dir"] + "/logs", create=True, private=True)
    try:
        fd = os.open("launcher.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                     0o600, dir_fd=log_fd)
        with os.fdopen(fd, "ab") as log:
            # runuser restores the original account rather than launching as root.
            entry = dict(command=f'{runuser} -m -u {helper.shlex.quote(launch["user"])} -- '
                         f'{helper.shlex.quote(argv[0])} [原始启动参数保存在目标机器]',
                         executable=argv[0], status="attempted", count=1, arguments_hidden=True)
            if helper.TRACE_ENABLED:
                helper.COMMAND_TRACE.append(entry)
            process = subprocess.Popen([runuser, "-m", "-u", launch["user"], "--", *argv],
                cwd=launch.get("cwd") or account.pw_dir, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, close_fds=True)
            entry["status"] = "started"
            return process
    finally:
        os.close(log_fd)


def external_mount_lifecycle(req, helper):
    if os.geteuid() != 0:
        raise ValueError("管理已有客户端需要 sudo 认证")
    record, action = req["record"], req["action"]
    identity = record.get("identity") or {}
    if not identity or not record.get("state_dir"):
        raise ValueError("缺少已扫描的客户端身份，请重新扫描")
    with helper.OwnedState(record["state_dir"], req["resource_id"] + ":external-mount", create=True) as store:
        state = store.load()
        # A new scan explicitly refreshes identity; old operation snapshots do not.
        expected = state.get("identity", identity) if state.get("scan_identity") == identity else identity
        mount, process = _external_verified(req, helper, expected)
        if process:
            launch = _external_capture(process, record)
            updated = dict(identity=expected, scan_identity=identity, process=process,
                           mount=mount, launch=launch, state="mounted")
            if len(json.dumps(updated).encode()) > 65536:
                raise ValueError("客户端启动参数过大，无法保存管理记录")
            store.save(updated)
            state = updated
        if action == "mount.status":
            return ("mounted" if mount else "unmounted"), {"mounted": bool(mount), "process_running": bool(process)}
        if action == "mount.logs":
            if not record.get("log_dir"):
                raise ValueError("客户端未指定可识别的日志目录")
            return "ready", helper.read_logs(req)
        if action == "mount.delete":
            if mount or helper.same_process(state.get("process"), helper.process_identity(expected.get("pid"))):
                raise ValueError("客户端仍挂载或运行，不能删除记录")
            return "deleted", {"mount_path": record["mount_path"], "data_preserved": True}
        if action == "mount.unmount":
            if mount:
                # Revalidate immediately before the system unmount; no dingo installation required.
                _external_verified(req, helper, expected)
                helper.run_command(["umount", "-l", "--", record["mount_path"]], timeout=30)
                if helper.mount_identity(record["mount_path"]):
                    raise ValueError("卸载后挂载点仍存在，请刷新检查")
            state["state"] = "unmounted"
            store.save(state)
            return "unmounted", {"mount_path": record["mount_path"]}
        if action == "mount.remount":
            if not mount and helper.same_process(state.get("process"), helper.process_identity(expected.get("pid"))):
                raise ValueError("上一个客户端进程仍未退出，请稍后重新挂载")
            _external_launch(req, helper, state.get("launch"))
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                rows = helper.scan_mounts(req["mds_addr"])["mounts"]
                candidates = [row for row in rows if row["mount_path"] == record["mount_path"]
                    and row["cluster_match"] == "current" and row["fs_name"] == record["fs_name"]
                    and row.get("identity") and row["identity"] != expected]
                if len(candidates) == 1:
                    successor = candidates[0]
                    new_mount, new_process = _external_verified(req, helper, successor["identity"])
                    if mount and new_mount != mount:
                        raise ValueError("热更新期间挂载身份变化，请重新扫描确认")
                    state.update(identity=successor["identity"], process=new_process,
                                 mount=new_mount, state="mounted")
                    store.save(state)
                    return "mounted", {"mount_path": record["mount_path"], "hot_updated": bool(mount)}
                time.sleep(0.5)
            raise ValueError("重新挂载未在 45 秒内完成，请查看客户端日志")
    raise ValueError("不支持的外部客户端操作")
