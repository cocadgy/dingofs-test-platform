"""One click install: SCP first, target registry pull only on transfer failure."""
import hashlib
import json
from pathlib import Path
import time
from .remote import install_script, probe_script
from .ssh_session import Remote

DTT_IMAGE='harbor.zetyun.cn/dingofs/dingofs-testsuite-tools:latest'


def choose_image(transfer, pull):
    try:
        return {**transfer(),'method':'platform-transfer'}
    except Exception as exc:
        transfer_error=str(exc)
    try:
        result=pull()
    except Exception as exc:
        raise RuntimeError("SCP 部署失败："+transfer_error+"；目标镜像拉取失败："+str(exc)) from exc
    if not result.get('success'):
        raise RuntimeError('SCP 部署失败：'+transfer_error+'；目标镜像拉取失败：'+result.get('error','未知原因'))
    return {**result,'method':'registry','transfer_error':transfer_error}


def helper(request):
    return 'REQUEST = '+repr(request)+'\n'+Path(__file__).with_name('automatic_helper.py').read_text()


def deploy(target_config, source_config, options, timeout_s, report):
    deadline=time.monotonic()+timeout_s
    source=None
    target=Remote(target_config,deadline,report,'目标机器')
    exported=None
    try:
        identity=target.python(helper({'operation':'identity'}),'检查目标架构')
        source=Remote(source_config,deadline,report,'平台机器')
        metadata=source.python(helper({'operation':'source_files','directory':options['directory'],'tool':options['tool']}),'读取平台工具文件')
        if options['tool']!='dtt' and metadata['architecture']!=identity['architecture']:
            raise RuntimeError('平台工具 CPU 架构与目标机器不匹配')
        files=metadata['files']
        size=sum(file['size'] for file in files.values())
        stage=target.python(helper({'operation':'stage','size_bytes':size}),'准备目标目录')['staging']
        scp_code=Path(__file__).with_name('scp_helper.py').read_text()
        def copy_file(name,file,timeout=None,progress_range=None):
            report(phase='SCP 传输 '+name,message=f'SCP 平台:{file["path"]} → 目标:{stage}/{name} ({file["size"]} bytes)\n')
            source.python(scp_code,'SCP 直传 '+name,input_data={
                'host':target_config.host,'port':target_config.port,
                'username':target_config.username,'password':target_config.password,
                'source':file['path'],'destination':stage+'/'+name,
                'timeout':timeout or max(1,min(source.remaining(),target.remaining())-15)},
                progress_range=progress_range)
        image={}
        if options['tool']=='dtt':
            def transfer_image():
                nonlocal exported,stage
                exported=source.python(helper({'operation':'export','image':options['image'],
                    'architecture':identity['architecture'],'pull_timeout':600,'save_timeout':300,
                    'allow_cached':options.get('allow_cached',False)}),'平台获取并导出镜像')
                stage=target.python(helper({'operation':'stage','size_bytes':size+exported['archive']['size']}),'准备镜像目标目录')['staging']
                # Reserve ten minutes for registry fallback and time for installation.
                budget=min(source.remaining(),target.remaining())-660
                if budget<=0:raise TimeoutError('SCP 时间预算不足，保留 Docker 拉取时间')
                copy_file('image.tar',exported['archive'],timeout=budget,progress_range=(10,70))
                return exported
            def pull_image():
                report(phase='SCP 失败，切换目标拉取',message='平台镜像 SCP 路径失败，改为目标机器拉取镜像（超时 600 秒）。\n')
                # Exclude any incomplete tar from the fallback installation.
                with target.sftp() as dst:
                    try:dst.remove(stage+'/image.tar')
                    except FileNotFoundError:pass
                    except OSError as exc:
                        if getattr(exc,'errno',None)!=2:raise
                return target.python(helper({'operation':'pull','image':options['image'],'pull_timeout':600}),'目标机器拉取镜像（最多10分钟）')
            image=choose_image(transfer_image,pull_image)
            if image.get('transfer_error'):report(message='SCP 回退原因：'+image['transfer_error']+'\n')
            if image.get('cached'):report(message='本次使用平台已有镜像，未确认仓库最新版本。\n')
        bundle={'tool':options['tool'],'version':image.get('image_id','files')[:80],
            'entrypoint':'dingofs-testsuite-tool' if options['tool']=='dtt' else options['tool'],
            'architecture':identity['architecture'],'files':{name:file['sha256'] for name,file in files.items()}}
        if image:bundle['image_id']=image['image_id']
        if image.get('method')=='platform-transfer' and exported:
            bundle['files']['image.tar']=exported['archive']['sha256']
            size+=exported['archive']['size']
        bundle['digest']=hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest()
        bundle['size_bytes']=size
        for name,file in files.items():
            try:
                copy_file(name,file)
            except Exception:
                # Small launchers are also required with a registry image. If direct
                # source-to-target SSH is unavailable, relay only these small files.
                report(message='启动文件 SCP 失败，使用 SFTP 中转：'+name+'\n')
                with source.sftp() as src,target.sftp() as dst:
                    with src.open(file['path'],'rb') as incoming,dst.open(stage+'/'+name,'wb') as outgoing:
                        while True:
                            source.remaining();target.remaining()
                            chunk=incoming.read(1024*1024)
                            if not chunk:break
                            outgoing.write(chunk)
        with target.sftp() as dst:
            with dst.open(stage+'/manifest.json','w') as manifest:
                manifest.write(json.dumps(bundle))
        report(progress=80)
        installed=target.python(install_script(bundle,stage),'校验并安装工具')
        report(progress=95)
        result=target.python(probe_script(),'验证已安装工具')
        selected=next(item for item in result['items'] if item['tool']==options['tool'])
        if selected['status']!='ready':raise RuntimeError('工具安装验证失败：'+selected['details'])
        return {**result,**installed,'method':image.get('method','platform-transfer'),
                'cached':image.get('cached',False),'image_id':image.get('image_id'),
                'transfer_error':image.get('transfer_error','')}
    finally:
        if exported and source:
            try:source.python(helper({'operation':'cleanup_export','path':exported['export_dir']}),'清理平台镜像临时文件')
            except Exception:report(message='平台导出临时文件未清理：'+exported['export_dir']+'\n')
        if source:source.close()
        target.close()
