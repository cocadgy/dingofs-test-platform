"""Resolve discovered cache members to authorized machines, never client-supplied PIDs."""
import ipaddress
from sqlalchemy import select
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.permissions import can_manage
from dingofs_platform.inventory.host_identity import normalize_host
from .models import ResourceOperation


def latest_members(db, cluster_id):
    op = db.scalar(select(ResourceOperation).where(
        ResourceOperation.cluster_id == cluster_id, ResourceOperation.action == 'cache.list'
    ).order_by(ResourceOperation.created_at.desc()).limit(1))
    if not op or op.state != 'succeeded':
        raise Problem(422, 'cache_list_required', '请先成功刷新缓存组与成员列表，再操作外部成员')
    members = {}
    found = False
    for step in (op.result or {}).get('steps', []):
        data = step.get('data', {})
        body = data.get('members', data) if isinstance(data, dict) else {}
        if isinstance(body, dict):
            body = body.get('result', body)
        rows = body.get('members') if isinstance(body, dict) else None
        if not isinstance(rows, list):
            continue
        found = True
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('member_id'), str) or row['member_id'] in members:
                raise Problem(422, 'invalid_members', '成员列表包含缺失或重复 UUID，请刷新列表')
            members[row['member_id']] = row
    if not found:
        raise Problem(422, 'invalid_members', '无法识别成员列表，请刷新列表')
    return members


def machine_addresses(machine):
    values = [machine.address, *(machine.aliases or [])]
    for nic in (machine.hardware_info or {}).get('interfaces', []) or []:
        for address in nic.get('addresses', []):
            try:
                ip = ipaddress.ip_interface(address).ip
                if not ip.is_loopback and not ip.is_link_local and not ip.is_unspecified:
                    values.append(str(ip))
            except ValueError:
                continue
    result = set()
    for value in values:
        try:
            result.add(normalize_host(value))
        except ValueError:
            pass
    return result


def targets(db, actor, cluster):
    members = latest_members(db, cluster.id)
    machines = list(db.scalars(select(Machine).where(Machine.archived == False)))
    addresses = [(m, machine_addresses(m)) for m in machines]
    result = {}
    for mid, member in members.items():
        reason = None
        try:
            ip = str(ipaddress.ip_address(member.get('ip', '')))
            port = int(member.get('port', 0))
            if type(member.get('port')) is bool or not 1 <= port <= 65535:
                raise ValueError()
        except (ValueError, TypeError):
            result[mid] = {'can_stop': False, 'reason': '成员地址或端口无效，请刷新列表'}
            continue
        matches = [m for m, values in addresses if ip in values]
        machine = matches[0] if len(matches) == 1 else None
        if not matches:
            reason = f'未找到地址 {ip} 对应的机器资源，请登记机器或更新机器网卡信息/主机别名'
        elif len(matches) > 1:
            reason = f'地址 {ip} 匹配多台机器资源，请消除重复地址或别名'
        elif not can_manage(actor, cluster) or not can_manage(actor, machine):
            reason = '没有目标集群或机器的管理权限'
        elif not machine.ssh_password_ciphertext:
            reason = '请先配置目标机器的 SSH 密码'
        result[mid] = dict(can_stop=reason is None, reason=reason,
            machine_id=machine.id if machine else None,
            machine_name=machine.name if machine else None, target_user='root',
            record=dict(member_id=mid, group_name=member.get('group_name', ''), listen_ip=ip, listen_port=port))
    return result


def resolve_members(db, actor, cluster, ids):
    resolved = targets(db, actor, cluster)
    chosen = {}
    for mid in ids:
        target = resolved.get(mid)
        if not target or not target['can_stop']:
            reason = target['reason'] if target else '成员不在最新查询结果中，请刷新列表'
            raise Problem(422, 'external_member_unavailable', f'{mid}：{reason}')
        chosen[mid] = target
    return chosen


def public_targets(db, actor, cluster):
    try:
        return {mid: {k: v for k, v in target.items() if k != 'record'}
                for mid, target in targets(db, actor, cluster).items()}
    except Problem:
        return {}
