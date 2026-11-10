"""Read-only data for the existing-environment guide.

Compatibility uses the same exact-case source inspection as preflight. It never
probes SSH or installs tools; preflight remains the authority for launch.
"""
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.permissions import can_manage, require_manage
from dingofs_platform.functional.contracts import EnvironmentDescriptor
from dingofs_platform.functional.preflight import _target, resolve_submission


def metadata(db, actor, settings):
    clusters = []
    for cluster in db.query(Cluster).filter(Cluster.archived == False):
        if not can_manage(actor, cluster):
            continue
        machine = db.get(Machine, cluster.management_machine_id)
        if not machine or not can_manage(actor, machine):
            continue
        clusters.append({
            'id': cluster.id, 'name': cluster.name,
            'mds_addresses': (cluster.status_snapshot or {}).get('mds_addresses') or [],
            'management_machine': {
                'id': machine.id, 'name': machine.name, 'address': machine.address,
                'ssh_user': machine.ssh_user,
            },
            'available': not machine.archived and not machine.maintenance,
        })
    machines = [{
        'id': machine.id, 'name': machine.name, 'address': machine.address,
        'ssh_user': machine.ssh_user, 'aliases': machine.aliases or [],
        'available': not machine.maintenance,
    } for machine in db.query(Machine).filter(Machine.archived == False)
        if can_manage(actor, machine)]
    return {'enabled': bool(settings.functional_guided_enabled),
            'clusters': clusters, 'machines': machines}


def compatibility(db, actor, payload, settings):
    if not settings.functional_guided_enabled:
        raise Problem(503, 'guided_runs_disabled', '引导功能测试尚未启用')
    cluster = db.get(Cluster, payload.cluster_id)
    if not cluster or cluster.archived:
        raise Problem(404, 'not_found', '集群不存在')
    require_manage(actor, cluster)
    control = db.get(Machine, cluster.management_machine_id)
    if not control or control.archived or control.maintenance:
        raise Problem(422, 'machine_unavailable', '管理机器不可用')
    require_manage(actor, control)
    db.info['functional_settings'] = settings
    resolved = resolve_submission(db, actor, payload)
    result = {}
    for plan in resolved.module_plans:
        descriptor = EnvironmentDescriptor.model_validate(
            resolved.environment_snapshots[plan.module])
        capability = descriptor.modules.get(plan.module)
        reasons = list(descriptor.issues)
        if not capability:
            reasons.append('测试框架未声明此模块能力')
        elif not capability.available:
            reasons.extend(capability.reasons or ['环境不支持已选用例'])
        if not descriptor.mds_addresses or set(descriptor.mds_addresses) != set(
                (cluster.status_snapshot or {}).get('mds_addresses') or []):
            reasons.append('环境目标与所选集群不一致')
        targets = []
        for target in descriptor.targets:
            try:
                machine = _target(db, actor, target.host)
                targets.append({'role': target.role, 'host': target.host, 'user': target.user,
                                'mutates': target.mutates, 'name': machine.name, 'address': machine.address})
                if target.user != machine.ssh_user:
                    reasons.append('执行用户与登记 SSH 用户不一致')
            except Problem:
                reasons.append('执行目标未登记或无管理权限')
        result[plan.module] = {
            'compatible': not reasons,
            'reasons': sorted(set(reasons)),
            'impacts': capability.impacts if capability else [],
            'targets': targets,
        }
    return {'modules': result}
