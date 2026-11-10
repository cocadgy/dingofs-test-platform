"""Normalize trusted source data and atomically persist idempotent queued runs.

No remote execution occurs here. Callers supply server-resolved, authorized
environment descriptors; raw client snapshots are never accepted by RunInputV2.
The caller owns the surrounding transaction and preflight validation.
"""
from copy import deepcopy
import hashlib
import json
from dataclasses import asdict
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dingofs_platform.auth.models import User
from dingofs_platform.errors import Problem
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.permissions import require_manage
from dingofs_platform.inventory.service import audit
from dingofs_platform.operations.models import OperationLease  # noqa: F401 register shared metadata
from dingofs_platform.operations.leases import functional_requests, require_available
from .contracts import EnvironmentDescriptor
from .drafts import Draft
from .models import FunctionalRun, FunctionalModuleRun
from .schemas import ModuleSelection, RunInput, RunInputV2, RunSpec
from .results import evaluate_child


class NormalizedSubmission(RunSpec):
    request_digest: str
    environment_snapshots: dict[str, dict]
    case_hashes: dict[str, dict[str, str]]
    idempotency_key: str | None = None
    preflight_token: str | None = Field(default=None, repr=False)
    confirmed_impacts: list[str] = Field(default_factory=list)
    draft_id: str | None = None
    draft_revision: int | None = None


def _digest(canonical: dict) -> str:
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def normalize_submission(payload: RunInput | RunSpec | RunInputV2, catalog: dict,
                         environments: dict[str, dict], *,
                         module_environments: dict[str, dict] | None = None) -> NormalizedSubmission:
    if payload.catalog_digest != catalog['digest']:
        raise Problem(409, 'catalog_changed', '用例目录已改变，请重新预检')
    if isinstance(payload, RunInput):
        if payload.wizard or payload.binaries:
            raise Problem(422, 'unsupported_environment', '引导任务仅支持已存在环境')
        profile_id = payload.environment_profile_id
        if not profile_id:
            matches = [key for key, env in environments.items() if env.get('env_name') == payload.env_name]
            if len(matches) != 1:
                raise Problem(422, 'environment_ambiguous', '无法唯一识别旧环境')
            profile_id = matches[0]
        env = environments.get(profile_id)
        if not env:
            raise Problem(404, 'environment_missing', '环境不存在')
        revision = payload.environment_profile_revision or env['revision']
        spec = RunSpec(name=payload.name, cluster_id=payload.cluster_id,
                       catalog_digest=payload.catalog_digest, retries=payload.retries,
                       timeout_minutes=payload.timeout_minutes,
                       module_plans=[ModuleSelection(module=module, cases=cases,
                           environment_profile_id=profile_id, environment_profile_revision=revision)
                           for module, cases in payload.selected.items()])
    else:
        spec = RunSpec(**payload.model_dump(include=set(RunSpec.model_fields)))
    snapshots, hashes = {}, {}
    for plan in spec.module_plans:
        source = (module_environments.get(plan.module) if module_environments is not None
                  else environments.get(plan.environment_profile_id))
        if not source:
            raise Problem(404, 'environment_missing', '环境不存在')
        if source.get('revision') != plan.environment_profile_revision:
            raise Problem(409, 'environment_changed', '环境版本已改变')
        descriptor = EnvironmentDescriptor.model_validate(source)
        snapshots[plan.module] = {'id': plan.environment_profile_id,
                                  'revision': plan.environment_profile_revision,
                                  **descriptor.model_dump(mode='json')}
        known = {row['path']: row['sha256'] for row in catalog['modules'].get(plan.module, [])}
        if not set(plan.cases) <= known.keys():
            raise Problem(422, 'invalid_cases', '用例不存在')
        hashes[plan.module] = {path: known[path] for path in plan.cases}
    canonical = {**spec.model_dump(mode='json'), 'environment_snapshots': snapshots, 'case_hashes': hashes}
    digest = _digest(canonical)
    controls = {key: getattr(payload, key) for key in (
        'idempotency_key', 'preflight_token', 'confirmed_impacts', 'draft_id', 'draft_revision')
        if hasattr(payload, key)}
    return NormalizedSubmission(**deepcopy(canonical), request_digest=digest, **controls)


def create_run(db: Session, actor: User, request: NormalizedSubmission, *,
               runtime_binding: dict | None = None, rerun_of: str | None = None,
               rerun_failed_only: bool = False) -> FunctionalRun:
    canonical = request.model_dump(mode='json', include={
        *RunSpec.model_fields, 'environment_snapshots', 'case_hashes'})
    if _digest(canonical) != request.request_digest:
        raise Problem(409, 'request_changed', '预检后请求快照发生变化')
    if not request.idempotency_key:
        raise Problem(422, 'idempotency_required', '提交需要幂等键')

    def existing():
        row = db.scalar(select(FunctionalRun).where(FunctionalRun.creator_id == actor.id,
                        FunctionalRun.idempotency_key == request.idempotency_key))
        if row:
            require_manage(actor, row)
        if row and row.request_digest != request.request_digest:
            raise Problem(409, 'idempotency_conflict', '幂等键已经用于不同的请求')
        return row

    prior = existing()
    if prior:
        return prior
    cluster = db.get(Cluster, request.cluster_id)
    if not cluster or cluster.archived:
        raise Problem(404, 'not_found', '集群不存在或已归档')
    require_manage(actor, cluster)
    machine = db.get(Machine, cluster.management_machine_id)
    if not machine or machine.archived or machine.maintenance:
        raise Problem(409, 'machine_unavailable', '集群管理机器不可用')
    require_manage(actor, machine)
    require_available(db, functional_requests(db, cluster.id, machine.id,
                      request.environment_snapshots.values(), actor=actor))
    # Savepoint keeps a concurrent uniqueness loser usable in its outer transaction.
    try:
        with db.begin_nested():
            draft = None
            if request.draft_id:
                draft = db.get(Draft, request.draft_id, with_for_update=True)
                if not draft or draft.creator_id != actor.id:
                    raise Problem(404, 'not_found', '草稿不存在')
                if draft.state != 'draft' or draft.revision != request.draft_revision:
                    # A duplicate may have been committed while waiting for the draft lock.
                    prior = existing()
                    if prior:
                        return prior
                    raise Problem(409, 'revision_conflict', '草稿已提交或版本发生变化')
            snapshot = request.model_dump(mode='json', exclude={
                'preflight_token', 'idempotency_key', 'confirmed_impacts', 'draft_id', 'draft_revision'})
            if runtime_binding is not None:
                snapshot['runtime_binding'] = deepcopy(runtime_binding)
            if rerun_of is not None:
                snapshot.update(rerun_of=rerun_of, rerun_failed_only=rerun_failed_only)
            row = FunctionalRun(version=2, creator_id=actor.id, cluster_id=cluster.id,
                                machine_id=machine.id, name=request.name, state='queued',
                                snapshot=deepcopy(snapshot), deadline=None,
                                idempotency_key=request.idempotency_key, request_digest=request.request_digest)
            db.add(row)
            db.flush()
            for position, plan in enumerate(request.module_plans):
                child_id = str(uuid4())
                pending = evaluate_child({'parent_id': row.id, 'child_id': child_id,
                                          'module': plan.module, 'cases': list(plan.cases)}, [], {})
                db.add(FunctionalModuleRun(id=child_id, run_id=row.id, module=plan.module, position=position,
                    environment_snapshot=deepcopy(request.environment_snapshots[plan.module]),
                    cases=list(plan.cases), case_hashes=deepcopy(request.case_hashes[plan.module]),
                    retries=request.retries, timeout_minutes=request.timeout_minutes, result=asdict(pending)))
            if draft:
                draft.state = 'submitted'; draft.run_id = row.id; draft.revision += 1
            audit(db, actor, 'functional.create', 'functional/' + row.id, [])
            db.flush()
        return row
    except IntegrityError:
        prior = existing()
        if prior:
            return prior
        raise
