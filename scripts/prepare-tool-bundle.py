#!/usr/bin/env python3
"""Prepare immutable offline tools from local files. Never downloads or starts services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4194304), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=['dtt','dingo','dingo-client','dingo-cache'], required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--source', type=Path, required=True, help='dtt 仓库目录；其他工具为可执行文件路径')
    parser.add_argument('--architecture', choices=['x86_64','aarch64'], default='x86_64')
    parser.add_argument('--image', help='平台已有的 dtt 容器镜像名（不会拉取）')
    parser.add_argument('--runtime', choices=['docker','podman'], default='docker')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'tool-bundles')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,80}', args.version):
        parser.error('版本只能包含字母、数字、点、横线、下划线、加号')
    args.output.mkdir(parents=True, exist_ok=True)
    name = f'{args.tool}-{args.version}-{args.architecture}'
    destination = args.output / name
    if destination.exists():
        parser.error('目标版本目录已存在，请使用新的版本号')
    stage = Path(tempfile.mkdtemp(prefix='.prepare-', dir=args.output))
    try:
        manifest = {'tool':args.tool,'version':args.version,'architecture':args.architecture}
        if args.tool == 'dtt':
            if not args.image:
                parser.error('dtt 必须通过 --image 指定本机已有镜像')
            inspect = json.loads(subprocess.check_output([args.runtime,'image','inspect',args.image]))[0]
            architecture = {'amd64':'x86_64','arm64':'aarch64'}.get(inspect['Architecture'])
            if architecture != args.architecture or inspect['Os'] != 'linux':
                raise ValueError('镜像系统或 CPU 架构与指定架构不匹配')
            manifest['image_id'] = inspect['Id']
            manifest['entrypoint'] = 'dingofs-testsuite-tool'
            for name in ('dingofs-testsuite-tool','dtt-ai-analyze','analysis.schema.json'):
                shutil.copyfile(args.source/name, stage/name)
            print('导出 dtt 镜像，包含 fio、elbencho…', flush=True)
            subprocess.run([args.runtime,'save','-o',str(stage/'image.tar'),manifest['image_id']],check=True)
        else:
            manifest['entrypoint'] = args.tool
            shutil.copyfile(args.source, stage/args.tool)
        manifest['files'] = {p.name:digest(p) for p in sorted(stage.iterdir())}
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for path in stage.iterdir():
            path.chmod(0o644)
        stage.chmod(0o755)
        os.rename(stage,destination)
        print('已生成：' + str(destination))
        print('在配置管理 → 工具包管理中登记：' + destination.name)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == '__main__':
    main()
