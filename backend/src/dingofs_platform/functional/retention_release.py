"""Explicit administrator retention acknowledgement; never claims cleanup."""
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from pydantic import BaseModel, ConfigDict, Field

from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.ssh_transport import SSHConfig
from dingofs_platform.inventory.service import audit
from dingofs_platform.operations.models import OperationLease
from dingofs_platform.operations.leases import LeaseRequest, lock_keys, ensure_leases
from .models import FunctionalRun, FunctionalModuleRun, FunctionalResource, ACTIVE
from .retention import child_ended, cleanup_in_progress
from .scheduler import _payload
from .transport import Transport


class RetentionConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: bool = Field(strict=True)


def verify_remote_end(db, parent, child):
    if child.state == 'not_run' and child.launch_attempted_at is None:
        return
    binding = parent.snapshot['runtime_binding']
    machine = db.get(Machine, parent.machine_id)
    connection = binding['control_connection']
    if (not machine or machine.archived or
            [machine.address, machine.ssh_port, machine.ssh_user] != connection):
        raise ValueError('control connection changed')
    settings = db.info['functional_settings']
    config = SSHConfig(*connection, decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key))
    transport = db.info.get('functional_transport', Transport)(config)
    identity = child.remote_identity
    observed = transport.poll_child(_payload(parent, child), identity.get('cursor', {}), False)
    if (observed.get('missing') or observed.get('protocol_error') or observed.get('transport_error')
            or observed.get('has_more') or not observed.get('journal_verified')
            or (observed.get('event_batch') or {}).get('partial_tail')):
        raise ValueError('remote outcome unverified')
    probe = SimpleNamespace(id=child.id, state=child.state, launch_attempted_at=child.launch_attempted_at,
                            remote_identity={**identity, 'remote_state': observed})
    if not child_ended(probe):
        raise ValueError('missing remote end proof')
    saved = identity['remote_state']
    if (observed['end_proof'] != saved['end_proof'] or observed['returncode'] != saved['returncode']
            or any(observed['process'].get(k) != saved['process'].get(k)
                   for k in ('child_id', 'launch_token', 'pid', 'start_time'))):
        raise ValueError('remote identity changed')
    process = observed['process']
    # Live /proc recheck supplements the durable supervisor end proof. A reused
    # PID is not this process; unreadable proc state never counts as absence.
    code = ('import json\nfrom pathlib import Path\n'
            f'pid={process["pid"]!r}\nexpected={process["start_time"]!r}\n'
            'try:\n    value=Path(f"/proc/{pid}/stat").read_text()\n'
            '    ended=value.rsplit(")",1)[1].split()[19] != str(expected)\n'
            'except FileNotFoundError:\n    ended=True\n'
            'except (OSError, ValueError, IndexError):\n    ended=False\n'
            'print(json.dumps({"ended":ended}))\n')
    if transport.call(code).get('ended') is not True:
        raise ValueError('original process may still be running')


def release_retained_run(db, actor, run_id, *, confirmed, reacquire=False):
    if actor.role != 'admin' or actor.disabled:
        raise Problem(403, 'admin_required', '仅管理员可以确认保留残留并调整占用')
    if confirmed is not True:
        raise Problem(422, 'confirmation_required', '请明确确认保留残留，不执行清理')
    owner = 'functional:' + run_id
    leases = list(db.scalars(select(OperationLease).where(OperationLease.owner == owner)))
    lock_keys(db, [LeaseRequest(row.key, row.mode) for row in leases])
    parent = db.get(FunctionalRun, run_id, with_for_update=True, populate_existing=True)
    if not parent or parent.version != 2:
        raise Problem(404, 'not_found', '引导任务不存在')
    children = list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id)
                              .with_for_update().execution_options(populate_existing=True)))
    if (parent.state in ACTIVE or not parent.finished_at or not children
            or not all(child_ended(child) for child in children)
            or cleanup_in_progress(db, run_id)):
        raise Problem(409, 'retention_end_unverified', '任务或关联清理尚未确认结束')
    if any(child.result.get('recovery_status') not in ('recovered', 'not_required')
           for child in children if child.launch_attempted_at is not None):
        raise Problem(409, 'retention_recovery_unverified', '环境恢复尚未确认，不能释放占用')
    marker = parent.result.get('retention_release') or {}
    held = list(db.scalars(select(OperationLease).where(OperationLease.owner == owner,
                       OperationLease.released_at.is_(None)).execution_options(populate_existing=True)))
    resources = list(db.scalars(select(FunctionalResource).where(
        FunctionalResource.child_id.in_([c.id for c in children]), FunctionalResource.phase != 'removed')))
    if not reacquire and not held and marker.get('released'):
        return marker
    if reacquire and not marker:
        raise Problem(409, 'retention_not_released', '该任务没有显式保留残留的释放记录')
    if reacquire and held and marker.get('released') is False:
        return marker
    if not reacquire and not held:
        raise Problem(409, 'retention_no_leases', '该任务没有待释放的占用')
    try:
        for child in children:
            verify_remote_end(db, parent, child)
    except Exception:
        raise Problem(409, 'retention_remote_unverified', '远端结束身份无法重新确认，未调整占用') from None
    timestamp = datetime.now(timezone.utc)
    if reacquire:
        requests = [LeaseRequest(item['key'], item['mode']) for item in marker['lease_requests']]
        if not ensure_leases(db, owner, requests).acquired:
            raise Problem(409, 'operation_conflict', '新任务正在占用资源，不能清理旧残留')
    else:
        requests = [LeaseRequest(row.key, row.mode) for row in held]
        for row in held:
            row.released_at, row.depth = timestamp, 0
    marker = {'released': not reacquire, 'released_keys': sorted({r.key for r in requests}),
              'lease_requests': [{'key': r.key, 'mode': r.mode} for r in requests],
              'retained_count': len(resources), 'actor_id': actor.id, 'observed_at': timestamp.isoformat(),
              'resources': [{'child_id': r.child_id, 'resource_id': r.resource_id, 'kind': r.kind, 'phase': r.phase}
                            for r in resources]}
    parent.result = {**parent.result, 'retention_release': marker}
    parent.phase = '残留已保留、占用已释放' if not reacquire else '已重新占用，等待残留清理'
    audit(db, actor, 'functional.retention.reacquire' if reacquire else 'functional.retention.release',
          'functional/' + run_id, marker['released_keys'])
    return marker
