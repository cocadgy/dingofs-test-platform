"""Atomic import and public views for functional environment profiles."""
from pathlib import PurePosixPath
from sqlalchemy import select
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.permissions import can_manage
from .importer import scan_predefined
from .models import FunctionalEnvironmentProfile as Profile

ALLOWED_SETTINGS={'mount_root','fs_prefix','cache_group','client_count','binaries','clients','remote_caches'}

def view(row, actor, db=None):
    result = {key:getattr(row,key) for key in (
        'id','name','source_kind','source_file','source_key','source_digest','creator_id',
        'cluster_id','machine_id','storage_profile_id','storage_profile_revision',
        'settings','display','revision','enabled','validation','created_at','updated_at')}
    result['display'] = dict(row.display or {})
    if row.source_kind == 'custom':
        settings = row.settings
        result['display'].update(
            client_count=sum(item.get('client_count', 1) for item in settings.get('clients', [{}])),
            cache_count=sum(item.get('remote_cache_count', 1) for item in settings.get('remote_caches', [])),
        )
    if db is not None and row.source_kind == 'custom':
        from dingofs_platform.inventory.models import Machine
        from dingofs_platform.storage.models import StorageProfile
        machine = db.get(Machine, row.machine_id) if row.machine_id else None
        storage = db.get(StorageProfile, row.storage_profile_id) if row.storage_profile_id else None
        members = [db.get(Machine, item['machine_id']) for item in row.settings.get('clients', [])]
        result['display'].update(machine_name=machine.name if machine else '',
                                 client_hosts=[member.address for member in members if member],
                                 storage_name=storage.name if storage else '')
    result['can_manage'] = row.source_kind == 'custom' and can_manage(actor, row)
    return result

def validate_settings(settings):
    if not isinstance(settings,dict):raise Problem(422,'invalid_settings','测试环境配置格式错误')
    if settings.keys()-ALLOWED_SETTINGS:raise Problem(422,'invalid_settings','测试环境包含不支持的字段')
    for key in ('mount_root','fs_prefix','cache_group'):
        if key in settings and (not isinstance(settings[key],str) or len(settings[key])>512 or any(c in settings[key] for c in '\n\r\x00')):
            raise Problem(422,'invalid_settings',key+' 格式错误')
    if 'client_count' in settings and (not isinstance(settings['client_count'],int) or isinstance(settings['client_count'],bool) or settings['client_count']!=1):
        raise Problem(422,'invalid_settings','第一版自定义环境仅支持单客户端')
    _member_settings(settings)
    if 'binaries' in settings:
        if not isinstance(settings['binaries'],dict) or settings['binaries'].keys()-{'dingo-client','dingo-cache','dingo-mds-client'}:
            raise Problem(422,'invalid_settings','二进制配置不支持')
        for path in settings['binaries'].values():
            if not isinstance(path,str) or not path.startswith('/') or '..' in PurePosixPath(path).parts or any(c in path for c in '\n\r\x00') or len(path)>512:
                raise Problem(422,'invalid_settings','二进制路径必须是安全的绝对路径')

def member_machine_ids(settings, default_machine_id):
    clients=settings.get('clients')
    ids={entry['machine_id'] for entry in clients} if clients is not None else {default_machine_id}
    ids.update(entry['machine_id'] for entry in settings.get('remote_caches',[]))
    return ids

_FLAG=__import__('re').compile(r'^--[a-zA-Z][a-zA-Z0-9_]*$')
_FORBIDDEN=__import__('re').compile(r'(^|_)(password|secret|token|credential|key|ak|sk)(_|$)')
def _member_settings(settings):
    for kind,count_key,conf_key in (('clients','client_count','client_conf'),('remote_caches','remote_cache_count','remote_cache_conf')):
        entries=settings.get(kind,[])
        if not isinstance(entries,list) or len(entries)>100 or (kind=='clients' and 'clients' in settings and not entries):
            raise Problem(422,'invalid_settings',kind+' 列表格式错误')
        allowed={'machine_id',count_key,conf_key,'dingo_tool_path'}
        if kind=='clients':allowed|={'fs_name','mount_path'}
        for item in entries:
            if not isinstance(item,dict) or item.keys()-allowed or not isinstance(item.get('machine_id'),str) or not item['machine_id']:
                raise Problem(422,'invalid_settings',kind+' 的机器配置错误')
            if 'dingo_tool_path' in item and (not isinstance(item['dingo_tool_path'],str) or len(item['dingo_tool_path'])>512 or any(c in item['dingo_tool_path'] for c in '\r\n\x00;|&$`')):
                raise Problem(422,'invalid_settings','dingo 工具路径格式错误')
            count=item.get(count_key,1)
            if not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=1000:
                raise Problem(422,'invalid_settings',kind+' 实例数量必须在 1 到 1000 之间')
            if kind=='clients':
                for key in ('mount_path','fs_name'):
                    if key in item and (not isinstance(item[key],str) or len(item[key])>512 or any(c in item[key] for c in '\r\n\x00')):
                        raise Problem(422,'invalid_settings',key+' 格式错误')
                path=item.get('mount_path','/')
                if not path.startswith('/') or '..' in PurePosixPath(path).parts:
                    raise Problem(422,'invalid_settings','客户端挂载路径必须是安全的绝对路径')
            conf=item.get(conf_key,{})
            if not isinstance(conf,dict) or len(conf)>100:
                raise Problem(422,'invalid_settings',conf_key+' 格式错误')
            for flag,value in conf.items():
                if not isinstance(flag,str) or not _FLAG.fullmatch(flag) or flag=='--mds_addrs' or _FORBIDDEN.search(flag[2:].lower()):
                    raise Problem(422,'invalid_settings','配置参数不受支持')
                if not isinstance(value,(str,int,bool)) or isinstance(value,str) and (len(value)>2048 or any(c in value for c in '\r\n\x00;|&$`')):
                    raise Problem(422,'invalid_settings','配置参数值格式错误')

def sync_predefined(db, root):
    descriptors=scan_predefined(root)
    keys={(d.source_file,d.key) for d in descriptors}
    current={(r.source_file,r.source_key):r for r in db.scalars(select(Profile).where(Profile.source_kind=='predefined'))}
    created=updated=0
    for item in descriptors:
        key=(item.source_file,item.key)
        row=current.get(key)
        display=dict(base=item.base,source_file_sha=item.source_file_sha,storage_file_sha=item.storage_file_sha,mds_addresses=item.mds_addresses,client_hosts=item.client_hosts,
                     storage_type=item.storage_type,client_count=item.client_count,cache_count=item.cache_count,template=item.template,issue=item.issue)
        if row is None:
            row=Profile(name=item.key,source_kind='predefined',source_file=item.source_file,
                        source_key=item.key,source_digest=item.source_digest,settings={},display=display,
                        enabled=item.runnable,validation='source_only' if item.runnable else ('template' if item.template else 'needs_completion'))
            db.add(row);created+=1
        elif row.source_digest!=item.source_digest or row.deleted:
            row.source_digest=item.source_digest;row.display=display;row.deleted=False
            row.enabled=item.runnable;row.validation='needs_validation' if item.runnable else ('template' if item.template else 'needs_completion')
            row.revision+=1;updated+=1
        elif row.display != display:
            row.display=display
    for key,row in current.items():
        if key not in keys and not row.deleted:
            row.enabled=False;row.validation='source_missing';row.revision+=1;updated+=1
    db.flush()
    return {'total':len(descriptors),'created':created,'updated':updated}
