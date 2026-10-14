"""Password SSH + streaming SFTP, one deadline for the whole deployment."""
import json
import shlex
import threading
import time
from pathlib import Path
import paramiko
from .remote import probe_script, install_script


def execute(config, bundle, root, timeout_s, report):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    deadline = time.monotonic() + timeout_s
    timer = threading.Timer(timeout_s, client.close)
    timer.daemon = True
    timer.start()

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('工具部署超时；请重新检查目标机器上的工具状态')
        return left

    def run(command, phase):
        report(phase=phase, message='$ ' + command[:4000] + '\n')
        channel = client.get_transport().open_session(timeout=min(15, remaining()))
        output = bytearray()
        try:
            channel.settimeout(min(30, remaining()))
            channel.exec_command(command)
            channel.shutdown_write()
            while True:
                remaining()
                ready = False
                for is_ready, read in ((channel.recv_ready, channel.recv), (channel.recv_stderr_ready, channel.recv_stderr)):
                    if is_ready():
                        chunk = read(16384)
                        output.extend(chunk)
                        if len(output) > 1024 * 1024:
                            raise RuntimeError('工具输出超过 1 MiB 限制')
                        report(message=chunk.decode(errors='replace'))
                        ready = True
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if not ready:
                    time.sleep(0.05)
            if channel.recv_exit_status() != 0:
                raise RuntimeError('远端命令失败：' + output.decode(errors='replace')[-4000:])
            return output.decode(errors='replace')
        finally:
            channel.close()

    def python(code, phase):
        # GNU timeout also bounds remote child processes if the API disconnects.
        command = 'timeout --signal=TERM --kill-after=10s ' + str(max(1, int(remaining()) - 10)) + 's python3 -c ' + shlex.quote(code)
        return run('bash -lc ' + shlex.quote(command), phase)

    try:
        client.connect(config.host, port=config.port, username=config.username, password=config.password,
                       allow_agent=False, look_for_keys=False, timeout=min(15, remaining()),
                       auth_timeout=min(15, remaining()), banner_timeout=min(15, remaining()))
        if bundle:
            report(phase='检查架构和暂存目录', progress=3)
            prelude = "import os,platform,tempfile,json,shutil; from pathlib import Path; "
            prelude += "assert platform.machine()==" + repr(bundle['architecture']) + ", '工具包 CPU 架构不匹配'; "
            prelude += "root=Path.home()/'.local/share/dingofs-platform/staging'; root.mkdir(parents=True,exist_ok=True); "
            prelude += "assert shutil.disk_usage(root).free > " + str(bundle["size_bytes"] + 536870912) + ", '暂存目录可用空间不足'; "
            prelude += "print(json.dumps({'staging':tempfile.mkdtemp(prefix='deploy-',dir=root)}))"
            response = python(prelude, '检查目标机器')
            staging = json.loads(response.strip().splitlines()[-1])['staging']
            sftp = client.open_sftp()
            sftp.get_channel().settimeout(min(30, remaining()))
            try:
                transferred = 0
                last = 0
                total = bundle['size_bytes']
                for name in (*bundle['files'], 'manifest.json'):
                    relative = Path(name)
                    for parent in reversed(relative.parents):
                        if str(parent) == '.':
                            continue
                        try:
                            sftp.mkdir(staging + '/' + str(parent))
                        except OSError:
                            sftp.stat(staging + '/' + str(parent))
                    report(phase='传输 ' + name, message='SFTP ' + name + ' → ' + staging + '/' + name + '\n')
                    base = transferred

                    def progress(count, size):
                        nonlocal last
                        remaining()
                        if time.monotonic() - last >= 1:
                            report(progress=min(75, 5 + int(70 * (base + count) / max(1, total))))
                            last = time.monotonic()
                    source = Path(root) / bundle['directory'] / name
                    sftp.put(str(source), staging + '/' + name, callback=progress)
                    transferred += source.stat().st_size
            finally:
                sftp.close()
            report(phase='校验和激活工具', progress=80)
            output = python(install_script(bundle, staging), '校验文件、验证运行依赖并安装')
            installed = json.loads(output.strip().splitlines()[-1])
        else:
            installed = {}
        report(phase='检查工具状态', progress=95)
        result = python(probe_script(), '检查工具状态')
        snapshot = json.loads(result.strip().splitlines()[-1])
        if bundle:
            selected = next(item for item in snapshot['items'] if item['tool'] == bundle['tool'])
            if selected['status'] != 'ready':
                raise RuntimeError('安装后验证失败：' + selected['details'])
        return {**snapshot, **installed}
    finally:
        timer.cancel()
        client.close()
