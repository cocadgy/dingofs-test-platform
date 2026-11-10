"""Executed on source/target by the automatic deployer. REQUEST is injected."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
import shlex


def command(argv, timeout=120):
    print('$ '+shlex.join(argv), flush=True)
    try:
        p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        text=p.stdout.decode(errors='replace')[-16000:]
        print(text,flush=True)
        return p.returncode,text
    except subprocess.TimeoutExpired:
        print('命令超时',flush=True)
        return 124,'命令超时'


def runtime():
    value=shutil.which('docker') or shutil.which('podman')
    if not value:raise RuntimeError('缺少 Docker/Podman，请先安装容器运行环境')
    rc,text=command([value,'info'])
    if rc:raise RuntimeError('容器运行环境不可用：'+text)
    return value


def inspect(engine, image):
    rc,text=command([engine,'image','inspect','--format','{{.Id}} {{.Architecture}}',image])
    if rc:return None
    identifier,architecture=text.strip().split()
    return {'image_id':identifier,'architecture':{'amd64':'x86_64','arm64':'aarch64'}.get(architecture,architecture)}


def file_info(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4194304),b''):digest.update(chunk)
    return {'path':str(path),'sha256':digest.hexdigest(),'size':path.stat().st_size}


op=REQUEST['operation']
if op=='pull':
    engine=runtime()
    rc,error=command([engine,'pull',REQUEST['image']], timeout=REQUEST.get('pull_timeout',600))
    image=inspect(engine,REQUEST['image']) if rc==0 else None
    if image and image['architecture']!=platform.machine():raise RuntimeError('拉取的镜像 CPU 架构不匹配')
    print(json.dumps({'success':bool(image),'error':error if not image else '',**(image or {})}))
elif op=='source_files':
    directory=Path(REQUEST['directory']).expanduser().resolve()
    tool=REQUEST['tool']
    names=['dingofs-testsuite-tool','dtt-ai-analyze','analysis.schema.json'] if tool=='dtt' else [tool]
    files={name:file_info(directory/name) for name in names}
    functional_metadata={}
    if tool=='dtt':
        runtime={'entrypoint.sh':directory/'entrypoint.sh',**{name:directory/'scripts'/name for name in ('performance_benchmark.py','performance_plan.py','performance_report.py','performance_tools.py')}}
        if all(path.is_file() for path in runtime.values()):
            files.update({name:file_info(path) for name,path in runtime.items()})
        functional={name:directory/'dingofs-integration-test'/path for name,path in {'run_tests.py':'run_tests.py','test_suite.py':'src/test_runner/test_suite.py','functional_plan.py':'src/test_runner/functional_plan.py','env_parser.py':'src/config/env_parser.py','env_setup.py':'src/config/env_setup.py','command_utils.py':'src/config/command_utils.py','client_mount_ops.py':'src/client_test/mixins/mount_ops.py','client_cache_group_ops.py':'src/client_test/mixins/cache_group_ops.py','large_scale_cache_setup.py':'src/large_scale_test/cache_setup.py','large_scale_cache_observer.py':'src/large_scale_test/cache_observer.py',**{name+'_executor.py':'src/'+name+'_test/executor.py' for name in ('mount_subdir','trash','cache_node','hot_upgrade','dirstat','mds_manage')}}.items()}
        if not (directory/'functional_runtime.py').exists() and all(path.is_file() for path in functional.values()):
            files.update({name:file_info(path) for name,path in functional.items()})
        metadata=directory/'scripts/ai_storage_scenarios.py'
        if metadata.is_file():files['ai_storage_scenarios.py']=file_info(metadata)
        if (directory/'functional_runtime.py').exists():
            source_files,source_manifest,source_aliases=functional_source_files(directory)
            files.update({name:file_info(path) for name,path in source_files.items()})
            functional_metadata={'source_manifest':source_manifest,'functional_features':FUNCTIONAL_FEATURES,'source_aliases':source_aliases}
    print(json.dumps({'architecture':platform.machine(),'files':files,**functional_metadata}))
elif op=='export':
    engine=runtime()
    rc,error=command([engine,'pull',REQUEST['image']], timeout=REQUEST.get('pull_timeout',600))
    cached=rc!=0
    if cached and not REQUEST.get('allow_cached',False):raise RuntimeError('平台也无法获取最新镜像；未允许使用平台已有镜像。'+error)
    image=inspect(engine,REQUEST['image'])
    if not image and cached:
        image=inspect(engine,'dingofs-testsuite-tools:latest')
    if not image:raise RuntimeError('平台机器没有可用的 dtt 镜像：'+error)
    if image['architecture']!=REQUEST['architecture']:raise RuntimeError('平台镜像 CPU 架构与目标机器不一致')
    root=Path.home()/'.local/share/dingofs-platform/exports'
    root.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='image-',dir=root))
    try:
        rc,text=command([engine,'save','-o',str(stage/'image.tar'),image['image_id']],timeout=REQUEST.get('save_timeout',1200))
        if rc:raise RuntimeError('平台镜像导出失败：'+text)
        print(json.dumps({**image,'cached':cached,'archive':file_info(stage/'image.tar'),'export_dir':str(stage)}))
    except BaseException:
        shutil.rmtree(stage)
        raise
elif op=='stage':
    root=Path.home()/'.local/share/dingofs-platform/staging'
    root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<REQUEST['size_bytes']+536870912:raise RuntimeError('目标机器暂存空间不足')
    print(json.dumps({'staging':tempfile.mkdtemp(prefix='auto-',dir=root),'architecture':platform.machine()}))
elif op=='identity':
    print(json.dumps({'architecture':platform.machine()}))
elif op=='parents':
    stage=Path(REQUEST['staging'])
    root=Path.home()/'.local/share/dingofs-platform/staging'
    relative=Path(REQUEST['name'])
    if stage.parent!=root or stage.is_symlink() or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid staging file path')
    destination=stage/relative
    for parent in reversed(destination.parent.parents):
        if parent==stage or stage in parent.parents:
            if parent.is_symlink():raise ValueError('Invalid staging symlink')
            parent.mkdir(mode=0o700,exist_ok=True)
            parent.chmod(0o700)
    if destination.parent.is_symlink():raise ValueError('Invalid staging symlink')
    destination.parent.mkdir(mode=0o700,exist_ok=True)
    destination.parent.chmod(0o700)
    print(json.dumps({'prepared':True}))
elif op=='cleanup_export':
    path=Path(REQUEST['path'])
    root=Path.home()/'.local/share/dingofs-platform/exports'
    if path.parent!=root or not path.name.startswith('image-') or path.is_symlink():raise RuntimeError('无效的导出清理路径')
    shutil.rmtree(path,ignore_errors=True)
    print(json.dumps({'cleaned':True}))
else:
    raise RuntimeError('不支持的工具操作')
