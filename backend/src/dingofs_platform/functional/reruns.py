"""Re-run only frozen, verified work after a new trusted preflight."""
from dingofs_platform.errors import Problem
from pydantic import BaseModel, ConfigDict, Field
from .schemas import RunSpec


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)


def rerun_spec(parent, children, *, failed_only):
    if parent.state not in ('success', 'failed') or parent.cancel_requested:
        raise Problem(409, 'rerun_unverified', '原任务尚未安全结束或已取消，请重新配置并预检')
    plans = []
    by_module = {child.module: child for child in children}
    for plan in parent.snapshot['module_plans']:
        child = by_module.get(plan['module'])
        if not child:
            raise Problem(409, 'rerun_unverified', '原任务模块记录不完整')
        result = child.result or {}
        if child.state == 'not_run' and child.launch_attempted_at is None:
            if not failed_only:
                plans.append(plan)
            continue
        if (child.state not in ('success', 'failed') or result.get('end_proof') is not True
                or result.get('cleanup_status') != 'cleaned'
                or result.get('recovery_status') not in ('recovered', 'not_required')
                or result.get('retained_resources')):
            raise Problem(409, 'rerun_unverified', '模块结束、清理或恢复尚未验证，请先处理残留')
        cases = list(plan['cases'])
        if failed_only:
            failed = {row['case_path'] for row in result.get('case_results', []) if row.get('status') == 'FAIL'}
            if (failed != set(result.get('failed_cases', [])) or not failed <= set(cases)
                    or failed & (set(result.get('missing', [])) | set(result.get('not_run', [])))):
                raise Problem(409, 'rerun_unverified', '失败用例记录不一致，请重新配置并预检')
            cases = [case for case in cases if case in failed]
        if cases:
            plans.append({**plan, 'cases': cases})
    if not plans:
        raise Problem(422, 'no_failed_cases', '没有明确失败的用例可重跑')
    fields = {key: parent.snapshot[key] for key in RunSpec.model_fields if key != 'module_plans'}
    return RunSpec(**{**fields, 'name': fields['name'][:105] + (' · 失败重跑' if failed_only else ' · 重跑'),
                      'module_plans': plans})


def require_same_source(original, current):
    for key in ('catalog_digest', 'environment_snapshots', 'case_hashes'):
        if original.get(key) != current.get(key):
            raise Problem(409, 'rerun_source_changed', '原始环境或用例版本已改变，请重新配置并预检')


def confirmed_rerun_impacts(original, required):
    if original is None or not set(required) <= set(original):
        raise Problem(409, 'rerun_confirmation_required', '影响已改变或原确认记录不可用，请重新配置并确认预检影响')
    return list(required)


def rerun_parent(db, actor, run_id, failed_only, idempotency_key):
    """Caller owns transaction; no browser-supplied evidence or mount reuse."""
    from sqlalchemy import and_, or_, select
    from dingofs_platform.auth.users import lock_accounts
    from dingofs_platform.inventory.permissions import require_manage
    from dingofs_platform.operations.models import OperationLease
    from .models import FunctionalRun, FunctionalModuleRun, FunctionalPreflight, FunctionalResource
    from .preflight import resolve_submission, revalidate_binding, preflight, validate_preflight
    from .submission import create_run, _digest
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise Problem(422, 'idempotency_required', '重跑需要有效幂等键')
    lock_accounts(db)
    original = db.get(FunctionalRun, run_id)
    if not original or original.version != 2:
        raise Problem(404, 'not_found', '原引导任务不存在')
    require_manage(actor, original)
    prior = db.scalar(select(FunctionalRun).where(FunctionalRun.creator_id == actor.id,
                      FunctionalRun.idempotency_key == idempotency_key))
    if prior:
        require_manage(actor, prior)
        if prior.snapshot.get('rerun_of') != run_id or prior.snapshot.get('rerun_failed_only') is not failed_only:
            raise Problem(409, 'idempotency_conflict', '幂等键已经用于不同重跑请求')
        return prior
    children = list(db.scalars(select(FunctionalModuleRun).where(FunctionalModuleRun.run_id == run_id)
                    .order_by(FunctionalModuleRun.position)))
    spec = rerun_spec(original, children, failed_only=failed_only)
    if db.scalar(select(FunctionalResource.id).join(FunctionalModuleRun,
        FunctionalResource.child_id == FunctionalModuleRun.id).where(FunctionalModuleRun.run_id == run_id,
        or_(FunctionalResource.phase.in_(('intent', 'retained', 'unknown')),
            and_(FunctionalResource.owned.is_(True), FunctionalResource.phase == 'active')))) or db.scalar(select(OperationLease.id).where(
        OperationLease.owner == 'functional:' + run_id, OperationLease.released_at.is_(None))):
        raise Problem(409, 'rerun_unverified', '原任务仍持有资源，请先完成残留复核')
    # Resolve the full original request first: even an unselected module's old
    # source must not silently become a different environment during a rerun.
    original_spec = RunSpec(**{key: original.snapshot[key] for key in RunSpec.model_fields})
    fresh_original = resolve_submission(db, actor, original_spec)
    require_same_source(original.snapshot, fresh_original.model_dump(mode='json'))
    revalidate_binding(db, actor, fresh_original, original.snapshot.get('runtime_binding'))
    old_tokens = list(db.scalars(select(FunctionalPreflight).where(FunctionalPreflight.consumed_by == run_id)))
    old_confirmed = (old_tokens[0].required_confirmations if len(old_tokens) == 1 and old_tokens[0].can_start
        and old_tokens[0].creator_id == original.creator_id
        and old_tokens[0].request_digest == original.request_digest
        and old_tokens[0].source_digest == _digest(original.snapshot['runtime_binding']) else None)
    normalized = resolve_submission(db, actor, spec)
    checked = preflight(db, actor, normalized)
    if not checked.can_start or not checked.token:
        raise Problem(409, 'rerun_preflight_failed', '新的只读预检未通过，请重新配置并预检')
    confirmed = confirmed_rerun_impacts(old_confirmed, checked.required_confirmations)
    normalized = normalized.model_copy(update={'idempotency_key': idempotency_key,
        'preflight_token': checked.token, 'confirmed_impacts': confirmed})
    gate = validate_preflight(db, actor, normalized, checked.token, confirmed)
    row = create_run(db, actor, normalized, runtime_binding=gate['runtime_binding'],
                     rerun_of=run_id, rerun_failed_only=failed_only)
    db.get(FunctionalPreflight, gate['preflight_id']).consumed_by = row.id
    db.flush()
    return row
