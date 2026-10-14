import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def run(argv, help_tool=None):
    print('$ ' + __import__('shlex').join(argv), flush=True)
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
    print(result.stdout.decode(errors='replace')[-16000:], flush=True)
    if not (help_succeeded(help_tool, result.returncode, result.stdout.decode(errors='replace')) if help_tool else result.returncode == 0):
        raise RuntimeError('命令执行失败，退出码 ' + str(result.returncode))


if platform.machine() != BUNDLE['architecture']:
    raise RuntimeError('工具包 CPU 架构与目标机器不匹配')
stage = Path(STAGING)
for name, expected in BUNDLE['files'].items():
    path = stage / name
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4194304), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError('传输后文件校验失败：' + name)
    if name != 'image.tar':
        path.chmod(0o755)
entry = stage / BUNDLE['entrypoint']
if BUNDLE['tool'] == 'dtt':
    runtime = shutil.which('docker') or shutil.which('podman')
    if not runtime:
        raise RuntimeError('缺少 Docker/Podman，请先安装并启动容器运行环境')
    run([runtime, 'info'])
    if (stage / 'image.tar').exists():
        run([runtime, 'load', '-i', str(stage / 'image.tar')])
    run([runtime, 'image', 'inspect', BUNDLE['image_id']])
    # Verify the bundled tools, without mounting any target directory.
    for executable in ('fio', 'elbencho'):
        run([runtime, 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', executable, BUNDLE['image_id'], '--version'])
    (stage / 'config').mkdir(exist_ok=True)
    (stage / 'config/image').write_text(BUNDLE['image_id'] + '\n')
    (stage / 'config/runtime').write_text(Path(runtime).name + '\n')
    # Wrapper isolates configuration from any pre-existing dtt installation.
    (stage / 'dtt').write_text('#!/bin/bash\nbase="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"\n'
        'export DINGOFS_TESTSUITE_CONFIG_DIR="$base/config"\n'
        'export DTT_AI_ANALYZER="$base/dtt-ai-analyze"\n'
        'exec "$base/' + BUNDLE['entrypoint'] + '" "$@"\n')
    if all((stage/name).is_file() for name in ('entrypoint.sh','performance_benchmark.py','performance_plan.py','performance_report.py','performance_tools.py')):
        wrapper=(stage/'dtt').read_text().replace('exec "$base/', 'export DTT_PERFORMANCE_RUNTIME_DIR="$base"\nexec "$base/')
        (stage/'dtt').write_text(wrapper)
    (stage / 'dtt').chmod(0o755)
    entry = stage / 'dtt'
run([str(entry), '--help'], BUNDLE['tool'])
if BUNDLE['tool'] == 'dtt':
    (stage / 'image.tar').unlink(missing_ok=True)  # Loaded in the runtime; avoid retaining a second multi-GiB copy.
root = Path.home() / '.local/share/dingofs-platform/tools' / BUNDLE['tool']
root.mkdir(parents=True, exist_ok=True)
# Each deployment has its own immutable directory; activate only after verification.
destination = root / (BUNDLE['digest'][:16] + '-' + stage.name)
os.replace(stage, destination)
link = root / ('.current-' + stage.name)
link.symlink_to(destination, target_is_directory=True)
os.replace(link, root / 'current')
shell_entry = {}
if BUNDLE['tool'] == 'dtt':
    print('配置 dtt 命令入口和用户 PATH', flush=True)
    shell_entry = install_shell_entry(Path.home())
    print('命令入口：' + shell_entry['command_path'], flush=True)
    for profile in shell_entry['shell_profiles']:
        print('更新 shell 配置：' + profile, flush=True)
    for backup in shell_entry['backups']:
        print('已备份原文件：' + backup, flush=True)
    run([shell_entry['command_path'], '--help'])
    print('新终端可直接使用 dtt；已打开的 Bash 终端请执行 source ~/.bashrc，Zsh 执行 source ~/.zshrc。', flush=True)
print(json.dumps({'installed_path': str(root / 'current' / BUNDLE['tool']), 'version': BUNDLE['version'], **shell_entry}), flush=True)
