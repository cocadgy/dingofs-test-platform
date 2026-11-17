# Functional Test Environments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Put all predefined integration environments and reusable environments for new machines under Configuration Management, then let functional tasks run against either kind.

**Architecture:** Store environment metadata in a dedicated versioned platform table. Preserve predefined YAML as read-only source and import its 100 top-level keys; build custom task YAML from cluster, machine and storage profiles at execution time. Extend dtt with an exact environment-file mount, keeping the existing `env_name` CLI/API path compatible.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, React/TypeScript, ruamel.yaml, bash/dtt, pytest/Vitest.

**Spec:** `docs/superpowers/specs/2026-10-15-functional-test-environments-design.md`

## Global Constraints

- Saving or validating an environment never creates a filesystem, mount, or cache process.
- Only the 41 files in `dingofs-integration-test/conf/env/*.yaml` define predefined source entries; current expected count is 100 top-level names, including base templates.
- Predefined raw YAML and storage credentials never enter public API responses, plaintext database fields, audit events, or task logs.
- Custom environments start with one client; special cache/fault/large-scale modules require explicit capability checks.
- Existing `dtt --env <name>` and functional tasks using `env_name` continue to work.
- Preserve existing uncommitted changes in all three repositories; run only local fake-transport tests until the final controlled live verification.

## Review Focus

- Duplicate or cyclic `base` in imported YAML: scanning reports the conflicting key and synchronization does not partially publish records (Tasks 1–2 tests).
- Preset for another host/cluster: API rejects task creation instead of silently redirecting it (Task 3 test).
- Edited storage profile after task submission: task uses the frozen version or fails explicitly, never a changed backend (Task 4 test).
- dtt without environment-file support: task fails before test setup, never falls back to a similarly named preset (Task 5 test).
- Cancellation or failure during setup: temporary plaintext YAML is removed and its contents do not enter logs (Task 5 test).

---

### Task 1: Predefined environment parser

**Files:** Create `backend/src/dingofs_platform/functional/environments/importer.py`; test `backend/tests/test_functional_environment_importer.py`.

**Interfaces:** `scan_predefined(root: Path) -> list[PresetDescriptor]` returns source-relative file, key, base, SHA256, sanitized display fields, and `runnable` flag. `PresetDescriptor` is defined in the same file; persistence follows in Task 2.

- [x] Write failing tests for 100-key real-source inventory, base resolution, duplicate key, cycle, missing base, and secret absence from descriptors.
- [x] Run `docker run --rm ... python -m pytest -q tests/test_functional_environment_importer.py`; verify expected failures.
- [x] Use existing pinned ruamel.yaml safe mode and implement `scan_predefined`, mirroring integration parser precedence and inheritance.
- [x] Re-run focused tests; expect pass, record the result while preserving the shared dirty checkout.

### Task 2: Versioned environment records and API

**Files:** Create `backend/src/dingofs_platform/functional/environments/{models,schemas,service,routes}.py`, next Alembic migration; modify `backend/src/dingofs_platform/app.py`; test `backend/tests/test_functional_environment_api.py`.

**Interfaces:** `FunctionalEnvironmentProfile` has `source_kind`, `source_file`, `source_key`, `source_digest`, `creator_id`, `cluster_id`, `machine_id`, `storage_profile_id`, `settings`, `revision`, `enabled`, `validation` and timestamps. `GET/POST/PUT /api/v1/functional/environments`, `POST /{id}/copy`, `POST /sync-predefined`, `GET /{id}/validate` and `POST /{id}/preflight`; writes use optimistic `revision` and owner/admin checks. Predefined rows are read-only except copying. `sync_predefined(db: Session, root: Path) -> SyncResult` is atomic, idempotent, and never persists raw YAML.

- [x] Write failing API tests for list visibility, ownership, edit conflict, disabled storage profile, duplicate name, preset copy, source change/vanished source, import idempotency, and no credentials in JSON/DB/audit.
- [x] Run the tests against the isolated platform PostgreSQL test database; verify expected failures.
- [x] Implement migration, service and routes; add no cluster operations to save/copy/sync. Wire Task 1 importer to the sync route and deployment bootstrap command.
- [x] Run API and migration tests; expect pass, record the result while preserving the shared dirty checkout.

### Task 3: Configuration Management page and task selection

**Files:** Create `frontend/src/features/functional-environments/{FunctionalEnvironmentsPage.tsx,functional-environments.css,FunctionalEnvironmentsPage.test.tsx}`; modify `frontend/src/features/configuration/ConfigurationPage.tsx`, `frontend/src/features/functional/FunctionalPage.tsx`; test `frontend/src/features/functional/FunctionalPage.test.tsx`.

**Interfaces:** Environment list shows predefined/custom source, readiness, cluster/machine, storage, count and update time. Editor selects cluster, machine, storage profile, mount root, filesystem prefix, optional cache group and binaries. Functional task form sends `environment_profile_id` and `environment_profile_revision`; direct `env_name` remains available for legacy API clients.

- [x] Write failing UI tests for 100 preset rows, preset copy, invalid target warning, custom form, dirty-state protection, and task submit by profile ID.
- [x] Run `npm test -- --run` in `frontend`; verify expected failures.
- [x] Implement list/editor and configuration tab; make task page filter environments by selected cluster and block unverified/mismatched preset targets.
- [x] Run targeted Vitest and Docker web build; expect pass, record the result while preserving the shared dirty checkout.

### Task 4: Freeze, validate, and render custom environment config

**Files:** Create `backend/src/dingofs_platform/functional/environments/{render,validation}.py`; modify `backend/src/dingofs_platform/functional/{schemas,routes,manager}.py`; test `backend/tests/test_functional_environment_render.py`.

**Interfaces:** Task submission snapshots non-secret settings, machine/cluster IDs and storage profile ID+version. `render_environment(frozen, storage, ssh_password) -> str` produces a single-key YAML document for the integration parser. `validate_target(...)` checks target bindings and supported modules; the separate read-only preflight checks SSH, tools and mount-parent access.

- [x] Write failing tests for S3 and RADOS YAML accepted by the integration parser, one-client default, MDS binding, bad absolute path, unsupported module, wrong cluster, changed storage version, and secret-free task snapshot.
- [x] Run focused backend tests; verify expected failures.
- [x] Implement freeze/render/validation. Preserve `env_name` request path while new UI uses profile ID; perform permission and source-digest checks before enqueue.
- [x] Run backend/API tests; expect pass, record the result while preserving the shared dirty checkout.

### Task 5: Exact dtt environment-file execution

**Files:** Modify `dingofs-testsuite-tool/dingofs-testsuite-tool`, `dingofs-testsuite-tool/entrypoint.sh`, `backend/src/dingofs_platform/functional/{remote_runner,transport}.py`, `backend/src/dingofs_platform/tool_packages/automatic_helper.py`; test `dingofs-testsuite-tool/tests/test_functional_environment_cli.py` and `backend/tests/test_functional_environment_runner.py`.

**Interfaces:** dtt accepts `--int-env-file <absolute host path>` only for `-t int`, bind-mounts that file read-only as `/dingofs-integration-test/conf/env/env_platform_<id>.yaml`, and passes the exact generated environment key. Remote runner creates YAML mode 0600 inside the task directory, removes it in `finally`, and records only redacted diagnostics. Managed dtt installation ships the updated launcher and entrypoint.

- [x] Write failing fake-docker/runner tests for exact mount, missing file, unsupported/old runtime, path traversal, cancellation, setup failure, cleanup failure and secret redaction.
- [x] Run dtt and backend focused tests; verify expected failures.
- [x] Implement CLI/runner integration; do not pass YAML through shell interpolation or task log. Keep existing `--env` behavior unchanged.
- [x] Run focused tests and `bash -n`; expect pass, record the result while preserving the shared dirty checkout.

### Task 6: Integration, deployment, and controlled verification

**Files:** Modify `deploy/compose.yaml` if needed for source mount/bootstrap; add focused compatibility tests under `backend/tests/` and `frontend/src/features/functional/`.

**Interfaces:** Migrated platform shows all 100 predefined names; an unchanged predefined environment still submits a task; a newly created custom environment can run one read/write case on a controlled cluster and expose its Allure report.

- [x] Run importer against the real read-only source and assert 41 files/100 top-level entries, no duplicate IDs or leaked secrets.
- [x] Run focused backend, frontend, integration-parser and dtt tests; build api/web/migrate Docker images.
- [x] Apply migration and bootstrap sync; deploy api/web; verify predefined count and task-page selection by HTTP/API.
- [x] On an authorized target, run a single read/write case with a custom environment; verify filesystem creation, client mount, result, Allure summary and cleanup. If no suitable new machine is registered, use the previously authorized `main-dingofs` cluster for this controlled check and report that new-machine hardware was not tested.
- [x] Record verification and limitations in the final handoff; preserve unrelated uncommitted work; do not push unless requested.

### 增量实施：clients 与 remote_caches

1. 用 `env_29.yaml` 和 `env_parser.py` 确认数组、实例数量和参数字段；添加渲染与非法输入测试。
2. 扩展配置校验、机器权限校验、提交快照、启动时身份核验和预检。
3. 扩展配置页面，让用户逐项选择机器和常用参数，保留旧环境兼容。
4. 运行定向后端和前端测试，用真实集成测试解析器解析生成的 YAML，然后构建部署。
