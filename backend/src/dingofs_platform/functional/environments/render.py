"""Render one ephemeral integration environment. Never persist the output."""
from io import StringIO
import re
from ruamel.yaml import YAML

_MOUNT=re.compile(r'^/[A-Za-z0-9_./-]+$')
_NAME=re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,62}$')
_ENV=re.compile(r'^env_platform_[a-f0-9]{3,64}$')

def validate_custom_settings(settings):
    mount=settings.get('mount_root','')
    prefix=settings.get('fs_prefix','')
    if not isinstance(mount,str) or not _MOUNT.fullmatch(mount) or '..' in mount.split('/'):
        raise ValueError('挂载目录必须是安全的绝对路径')
    if not isinstance(prefix,str) or not _NAME.fullmatch(prefix):
        raise ValueError('文件系统前缀只能包含字母、数字、连字符和下划线')
    if settings.get('client_count',1)!=1 and 'clients' not in settings:
        raise ValueError('请在客户端列表中配置实例数量')

def render_environment(frozen, storage, ssh_password):
    settings=frozen['settings'];validate_custom_settings(settings)
    key=frozen['environment_key']
    if not _ENV.fullmatch(key):raise ValueError('invalid generated environment key')
    if storage['storage_type'] not in ('s3','rados'):raise ValueError('unsupported storage')
    backend={k:v for k,v in storage.items() if k!='storage_type'}
    hosts=frozen.get('machine_hosts',{})
    client_specs=settings.get('clients')
    if client_specs is None:
        client_specs=[{'machine_id':frozen.get('machine_id'),'mount_path':settings['mount_root'],
                       'client_count':1,'client_conf':{'--cache_group':settings['cache_group']} if settings.get('cache_group') else {}}]
    clients=[]
    for spec in client_specs:
        host=hosts.get(spec.get('machine_id')) or (frozen['client_host'] if spec.get('machine_id')==frozen.get('machine_id') else None)
        if not host:raise ValueError('客户端机器未绑定')
        conf=dict(spec.get('client_conf',{}))
        clients.append({'host':host,'fs_name':spec.get('fs_name') or settings['fs_prefix'],
                        'mount_path':spec.get('mount_path') or settings['mount_root'],
                        'client_count':spec.get('client_count',1),
                        'dingo_tool_path':spec.get('dingo_tool_path') or frozen.get('dingo_tool_path',''),'client_conf':conf})
    caches=[]
    for spec in settings.get('remote_caches',[]):
        host=hosts.get(spec.get('machine_id'))
        if not host:raise ValueError('缓存成员机器未绑定')
        conf={'--mds_addrs':frozen['mds_addr'],**spec.get('remote_cache_conf',{})}
        caches.append({'host':host,'remote_cache_count':spec.get('remote_cache_count',1),
                       'dingo_tool_path':spec.get('dingo_tool_path') or frozen.get('dingo_tool_path',''),
                       'remote_cache_conf':conf})
    value={'mds_addr':frozen['mds_addr'],'ssh_user':frozen['ssh_user'],
           'dingo_tool_path':frozen.get('dingo_tool_path',''),
           'run_as_user':frozen['ssh_user']+'/'+ssh_password if ssh_password else frozen['ssh_user'],
           'clients':clients,'remote_caches':caches,
           'storage':{'storage_type':storage['storage_type'],'partition_type':'hash',storage['storage_type']:backend}}
    yaml=YAML();yaml.default_flow_style=False
    output=StringIO();yaml.dump({key:value},output)
    return output.getvalue()
