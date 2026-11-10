"""Copy portable parameters, requiring explicit rebinding of machines and storage."""
from dingofs_platform.errors import Problem
from .importer import scan_predefined
from ..source_bridge import project_source


def preview(profile, root):
    if profile.source_kind != 'predefined':
        raise Problem(422, 'not_predefined', '仅预置环境需要复制配置预览')
    descriptor = next((item for item in scan_predefined(root) if item.key == profile.source_key and item.source_file == profile.source_file), None)
    if not descriptor or descriptor.source_digest != profile.source_digest:
        raise Problem(409, 'source_changed', '预置环境源文件已变化，请同步预置环境后重试')
    try:
        projection = project_source(root.parent.parent, profile.source_key)
    except ValueError:
        raise Problem(422, 'source_unavailable', '无法安全读取预置环境参数') from None
    if projection['digest'] != profile.source_digest:
        raise Problem(409, 'source_changed', '预置环境源文件已变化，请同步后重试')
    warnings = ['已继承客户端和缓存成员参数；请重新选择集群、执行机、各成员机器和存储。SSH 凭据及旧 MDS 地址不会复制。']
    if projection['omitted']:
        warnings.append('部分连接或不支持的参数未复制')
    return {'settings': projection['settings'], 'warnings': warnings}
