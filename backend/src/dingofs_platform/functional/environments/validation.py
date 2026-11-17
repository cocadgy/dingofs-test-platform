"""Pure, read-only target checks before enqueuing a functional run."""
from pathlib import Path
from dingofs_platform.errors import Problem
from .render import validate_custom_settings

SPECIAL_MODULES={'large_scale_cache','cache_node','fault','hot_upgrade','mds_manage'}

def validate_modules(modules):
    special=set(modules)&SPECIAL_MODULES
    if special:raise Problem(422,'environment_capability_required','普通自建环境不支持特殊模块：'+', '.join(sorted(special)))

def validate_target(row, cluster, machine, source_root, modules, known_hosts=None):
    if not row.enabled or row.deleted:raise Problem(422,'environment_unavailable','测试环境已停用')
    addresses=set((cluster.status_snapshot or {}).get('mds_addresses') or [])
    if row.source_kind=='custom':
        if row.cluster_id!=cluster.id or row.machine_id!=machine.id:
            raise Problem(422,'environment_target_mismatch','测试环境与目标集群或管理机器不一致')
        try:validate_custom_settings(row.settings)
        except ValueError as exc:raise Problem(422,'invalid_environment',str(exc)) from exc
        validate_modules(modules)
    else:
        from .importer import scan_predefined
        source=next((d for d in scan_predefined(Path(source_root).parent/'conf/env')
                     if d.key==row.source_key and d.source_file==row.source_file),None)
        if not source or source.source_digest!=row.source_digest:
            raise Problem(409,'environment_source_changed','预置环境源文件已变化，请先同步')
        if not source.runnable:raise Problem(422,'environment_template','基础模板不可直接运行')
        if set(source.mds_addresses)!=addresses:
            raise Problem(422,'environment_target_mismatch','预置环境的 MDS 地址与所选集群不一致')
        aliases=known_hosts if known_hosts is not None else {machine.address,machine.name,*machine.aliases}
        if not set(source.client_hosts)<=aliases:
            raise Problem(422,'environment_target_mismatch','预置环境的客户端主机与管理机器不一致')
