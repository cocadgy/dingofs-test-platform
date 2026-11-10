"""Admission-only classification. This never grants execution or releases leases."""
from sqlalchemy import select
from dingofs_platform.operations.models import OperationLease
from .models import FunctionalRun, FunctionalModuleRun, FunctionalResource


def queueable_conflicts(db, conflicts):
    if not conflicts:
        return False
    for owner in {c.owner for c in conflicts}:
        if not owner.startswith('functional:'):
            return False
        parent = db.get(FunctionalRun, owner[len('functional:'):], populate_existing=True)
        if not parent or parent.version != 2 or parent.state != 'running' or parent.cancel_requested:
            return False
        children = list(db.scalars(select(FunctionalModuleRun).where(
            FunctionalModuleRun.run_id == parent.id).execution_options(populate_existing=True)))
        running = [c for c in children if c.state == 'running']
        if len(running) != 1:
            return False
        child = running[0]
        identity = child.remote_identity
        process = identity.get('process', {})
        if (child.launch_attempted_at is None or child.cancel_requested or identity.get('protocol_error')
                or process.get('state') != 'running' or process.get('child_id') != child.id
                or not identity.get('launch_token') or process.get('launch_token') != identity['launch_token']
                or type(process.get('pid')) is not int or process['pid'] <= 0 or not process.get('start_time')):
            return False
        if any(c is not child and c.state != 'queued' and not c.result.get('may_continue') for c in children):
            return False
        if db.scalar(select(FunctionalResource.id).join(FunctionalModuleRun,
                FunctionalResource.child_id == FunctionalModuleRun.id).where(
                FunctionalModuleRun.run_id == parent.id,
                FunctionalResource.phase.in_(('intent', 'unknown', 'retained')))):
            return False
        # A matching owner prefix is insufficient: require the complete frozen
        # lease union, not a stale or fabricated single lease.
        from .scheduler import lease_requests
        held = {(row.key, row.mode) for row in db.scalars(select(OperationLease).where(
            OperationLease.owner == owner, OperationLease.released_at.is_(None), OperationLease.depth > 0))}
        try:
            if any((r.key, r.mode) not in held for r in lease_requests(parent)):
                return False
        except (KeyError, TypeError):
            return False
    return True
