"""Copy portable parameters, requiring explicit rebinding of machines and storage."""
from dingofs_platform.errors import Problem
from .importer import read_predefined, scan_predefined
from .service import _FLAG, _FORBIDDEN


def preview(profile, root):
    if profile.source_kind != 'predefined':
        raise Problem(422, 'not_predefined', '仅预置环境需要复制配置预览')
    descriptor = next((item for item in scan_predefined(root) if item.key == profile.source_key and item.source_file == profile.source_file), None)
    if not descriptor or descriptor.source_digest != profile.source_digest:
        raise Problem(409, 'source_changed', '预置环境源文件已变化，请同步预置环境后重试')
    _, resolved, _ = read_predefined(root)
    raw = resolved[profile.source_key]
    omitted = []

    def flags(value):
        result = {}
        for name, item in (value or {}).items():
            if (not isinstance(name, str) or not _FLAG.fullmatch(name) or name == '--mds_addrs'
                or _FORBIDDEN.search(name[2:].lower()) or not isinstance(item, (str, int, bool))
                or isinstance(item, str) and any(c in item for c in '\r\n\x00;|&$`')):
                omitted.append('部分连接或不支持的参数未复制')
            else:
                result[name] = item
        return result

    clients = []
    for item in raw.get('clients') or raw.get('hosts') or []:
        clients.append({'machine_id': '', 'client_count': item.get('client_count', 1),
                        'mount_path': item.get('mount_path') or '/tmp/dingofs-functional',
                        'fs_name': item.get('fs_name') or 'platform-test',
                        'client_conf': flags(item.get('client_conf'))})
    caches = [{'machine_id': '', 'remote_cache_count': item.get('remote_cache_count', 1),
               'remote_cache_conf': flags(item.get('remote_cache_conf'))}
              for item in raw.get('remote_caches') or []]
    settings = {'mount_root': clients[0]['mount_path'] if clients else '/tmp/dingofs-functional',
                'fs_prefix': clients[0]['fs_name'] if clients else 'platform-test',
                'clients': clients, 'remote_caches': caches, 'binaries': {}}
    return {'settings': settings, 'warnings': ['已继承客户端和缓存成员参数；请重新选择集群、执行机、各成员机器和存储。SSH 凭据及旧 MDS 地址不会复制。', *sorted(set(omitted))]}
