# Guided Start and Machine Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a “开始” workspace that guides a signed-in user through selecting a task and, for “添加机器”, validates password SSH and hardware collection before persisting the machine.

**Architecture:** A focused backend onboarding endpoint accepts only the five guided fields, runs the existing bounded password-SSH hardware probe before opening the final persistence transaction, and reuses existing validation, encryption, inventory locking, host identity, audit, and serialization. A new React feature owns the hash-routed task chooser, machine form, progress state, and success page; existing inventory pages and APIs stay unchanged.

**Tech Stack:** React 18, TypeScript, Vitest, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Paramiko, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-02-guided-start-machine-design.md`

## Global Constraints

- Preserve all unrelated changes in the already-dirty platform checkout; stage only files named by the active task.
- Keep the current default landing page for existing users; “开始” is an explicit left-navigation entry.
- Guided machine creation supports password SSH only and automatically trusts SSH host keys, matching current `ssh_transport.run_session` policy.
- Never put the SSH password in URLs, browser storage, responses, logs, audit details, exception messages, or test snapshots.
- SSH or wholly failed hardware collection creates no machine, host identifier, audit event, or credential row.
- `partial` hardware collection is a successful creation with unknown fields and a visible warning.
- Do not add SSH probe concurrency or frequency limits in this release.
- Do not change existing `/api/v1/machines`, refresh-hardware, inventory pages, or automated clients.
- “继续添加集群” remains disabled and marked “即将支持”; it must not redirect to the existing discovery page.

## Review Focus

- Two users submit the same normalized address and port while both probes are running: exactly one machine is committed and the other receives a safe 409.
- A password containing leading/trailing whitespace or shell-like text remains byte-for-byte intact for SSH and never appears in logs or API output.
- SSH succeeds but every hardware category is unavailable: return a classified failure and persist nothing; `partial` remains successful.
- The user session is revoked or changes while the remote probe runs: the final transaction re-authenticates and persists nothing.
- Navigation, refresh, back, logout, and session expiry clear the password while retaining only non-secret guided state where specified.

---

### Task 1: Atomic guided machine creation API

**Files:**
- Create: `backend/src/dingofs_platform/inventory/guided_routes.py`
- Modify: `backend/src/dingofs_platform/app.py`
- Test: `backend/tests/test_guided_machine_api.py`

**Interfaces:**
- Consumes: `MachineInput`, `SSHConfig`, `hardware.collect`, `credential_changes`, `lock_inventory`, `sync_host_identifiers`, `audit`, `serialize`, `actor_in_transaction`.
- Produces: `POST /api/v1/guided/machines` with `GuidedMachineInput` and a serialized machine response containing `hardware_info` and `collection_status`.

- [ ] **Step 1: Write failing API tests for validation and no-persist failures**

Add tests named `test_guided_machine_requires_five_fields`, `test_guided_machine_preserves_password_whitespace_for_transport`, `test_guided_machine_auth_failure_persists_nothing`, `test_guided_machine_connection_failure_is_classified`, and `test_guided_machine_total_hardware_failure_persists_nothing`. Use the app's injected `hardware_transport`; assert response bodies never contain the submitted password and the database contains no machine or audit event after failure.

- [ ] **Step 2: Run the failure tests and verify RED**

Run: `docker compose --env-file .env -f deploy/compose.yaml exec api python -m pytest -q tests/test_guided_machine_api.py`

Expected: FAIL because `/api/v1/guided/machines` does not exist.

- [ ] **Step 3: Define the guided request and bounded pre-persistence probe**

In `guided_routes.py`, define `GuidedMachineInput` with exactly `name`, `address`, `ssh_port=22`, `ssh_user`, and required `ssh_password`, applying the same limits and normalizers as `MachineInput`. Define `create_guided_machine(payload, request, user=Depends(current_user))`; build `SSHConfig` without trimming the password, invoke `collect(..., transport=request.app.state.hardware_transport or execute, timeout_s=settings.collection_timeout_seconds)`, map `CollectionError` through `ERRORS`, and reject `status == "failed"` without opening a persistence transaction.

- [ ] **Step 4: Persist only after a successful or partial probe**

After the probe, open `get_db(request)` with `db.begin()`, call `actor_in_transaction` to revalidate the current session, call `lock_inventory`, validate a full `MachineInput` with empty/default optional fields, encrypt through `credential_changes`, create `Machine` with `creator_id`, `hardware_info`, `last_attempt_info`, `last_attempt_at`, `last_success_at`, `collection_status`, and no active collection token, then call `sync_host_identifiers` and `audit(..., fields=["address", "name", "ssh_port", "ssh_user"])`. Flush and return `serialize`; rely on existing `IntegrityError` mapping for the final concurrent uniqueness check.

- [ ] **Step 5: Add success, partial, race, session-revocation, and redaction tests**

Add `test_guided_machine_success_saves_encrypted_password_and_snapshot`, `test_guided_machine_partial_succeeds_with_warning`, `test_guided_machine_duplicate_name_or_endpoint_returns_409`, `test_guided_machine_concurrent_duplicate_commits_once`, `test_guided_machine_reauthenticates_after_probe`, and `test_guided_machine_audit_and_response_exclude_password`. The concurrency test must coordinate two transports so both finish probing before either final transaction commits.

- [ ] **Step 6: Register the router and run backend verification**

Import and include the guided router in `backend/src/dingofs_platform/app.py`.

Run: `docker compose --env-file .env -f deploy/compose.yaml exec api python -m pytest -q tests/test_guided_machine_api.py tests/test_machine_collection.py tests/test_machine_credentials.py tests/test_machine_names.py tests/test_hardware.py`

Expected: all selected tests PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add backend/src/dingofs_platform/inventory/guided_routes.py \
  backend/src/dingofs_platform/app.py backend/tests/test_guided_machine_api.py
git commit -m "feat: add guided machine onboarding api"
```

### Task 2: Start navigation and task chooser

**Files:**
- Create: `frontend/src/features/getting-started/GettingStartedPage.tsx`
- Create: `frontend/src/features/getting-started/getting-started.css`
- Create: `frontend/src/features/getting-started/GettingStartedPage.test.tsx`
- Create: `frontend/src/features/getting-started/AppNavigation.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: current App hash navigation, authenticated session, and global dirty-state callback.
- Produces: `#/start`, `#/start/machine`, `GettingStartedPage({ route, onDirty })`, and the seven-action chooser.

- [ ] **Step 1: Write failing navigation and chooser tests**

Test that the left menu renders “开始” before “资源总览”; clicking it sets `#/start`; refresh/hash parsing renders the same page; the selector lists exactly 添加机器、添加集群、创建文件系统、创建缓存组、挂载文件系统、功能测试、性能测试; and choosing 添加机器 plus 下一步 navigates to `#/start/machine`.

- [ ] **Step 2: Run the frontend test and verify RED**

Run: `cd frontend && npm test -- --run src/features/getting-started/GettingStartedPage.test.tsx`

Expected: FAIL because the feature and route are absent.

- [ ] **Step 3: Implement the start route and chooser**

Create `GettingStartedPage` with a typed action list and `route` union (`"chooser" | "machine"`). Add `start` to App's hash synchronization, session initialization, navigation map, content-width class, and render branch without changing the default `dashboard` behavior. Keep future actions selectable; on 下一步 render an “即将支持” state with 返回开始页 rather than a dead control.

- [ ] **Step 4: Add dirty-navigation and session tests**

Verify that leaving a dirty machine form uses App's existing confirmation behavior and that logout/session expiry unmounts the start feature. Ensure no password is encoded into the hash or history state.

- [ ] **Step 5: Run focused and App tests**

Run: `cd frontend && npm test -- --run src/features/getting-started/GettingStartedPage.test.tsx src/features/getting-started/AppNavigation.test.tsx`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add frontend/src/App.tsx frontend/src/features/getting-started/
git commit -m "feat: add guided start workspace"
```

### Task 3: Guided machine form and completion page

**Files:**
- Create: `frontend/src/features/getting-started/GuidedMachineForm.tsx`
- Create: `frontend/src/features/getting-started/GuidedMachineForm.test.tsx`
- Modify: `frontend/src/features/getting-started/GettingStartedPage.tsx`
- Modify: `frontend/src/features/getting-started/getting-started.css`

**Interfaces:**
- Consumes: `POST /guided/machines` through `api`, App's `onDirty`, and the start route from Task 2.
- Produces: `GuidedMachineForm({ onDirty, onBack })`, progress states, safe error states, and the machine success summary.

- [ ] **Step 1: Write failing form validation and submission tests**

Test five required fields, default port 22, port range, SSH user pattern, password visibility control, disabled duplicate submission, exact request shape, and button labels 上一步 / 检查连接并添加. Assert leading/trailing password whitespace reaches the mocked API unchanged.

- [ ] **Step 2: Run the form test and verify RED**

Run: `cd frontend && npm test -- --run src/features/getting-started/GuidedMachineForm.test.tsx`

Expected: FAIL because `GuidedMachineForm` is absent.

- [ ] **Step 3: Implement form state and safe progress/error behavior**

Keep password only in component state and never in `localStorage`, `sessionStorage`, URL, error text, or persisted draft state. Render the agreed progress sequence while the single API request runs. Map server messages into field/global errors, retain non-secret fields after failure, and clear password on unmount, success, back navigation, and session-expired unmount.

- [ ] **Step 4: Implement success and partial summaries**

Render machine name, `ssh_user@address:ssh_port`, logical CPU cores, total memory, count of `disks` entries whose `type` is `disk`, RDMA availability, and `last_success_at`; show “未知” for missing fields. For `partial`, show an incomplete-information notice and a link to `#/machines/<id>`. Render 返回开始页 and a disabled `继续添加集群（即将支持）` button.

- [ ] **Step 5: Add failure, secret-lifecycle, partial, and accessibility tests**

Cover authentication failure, timeout, duplicate 409, total hardware failure, partial success, unknown summary values, unmount/back/session expiry clearing password, keyboard labels, live progress status, alert semantics, and focus moving to the first invalid field or result heading.

- [ ] **Step 6: Run frontend verification and production build**

Run: `cd frontend && npm test -- --run src/features/getting-started/GettingStartedPage.test.tsx src/features/getting-started/GuidedMachineForm.test.tsx src/features/getting-started/AppNavigation.test.tsx`

Run: `cd frontend && npm run build`

Expected: tests PASS and build exits 0.

- [ ] **Step 7: Commit Task 3**

```bash
git add frontend/src/features/getting-started/ frontend/src/App.tsx
git commit -m "feat: guide users through machine registration"
```

### Task 4: Compatibility, security verification, and deployment handoff

**Files:**
- Modify: `README.md`
- Create: `docs/GUIDED_START_ACCEPTANCE.md`
- Test: existing backend/frontend suites plus compose build.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: operator-facing acceptance steps and a deployable api/web build.

- [ ] **Step 1: Document the new workflow and boundaries**

Update README's current-delivery statement to include guided start and functional/performance tasks. In `GUIDED_START_ACCEPTANCE.md`, document the five fields, password-only and automatic-host-trust policy, no-persist failure behavior, partial hardware behavior, and disabled future add-cluster action.

- [ ] **Step 2: Run full backend and frontend suites**

Run: `docker compose --env-file .env -f deploy/compose.yaml exec api python -m pytest -q`

Run: `cd frontend && npm test -- --run`

Expected: both suites PASS; report any pre-existing failure by exact test name instead of hiding it.

- [ ] **Step 3: Build deployable images and run syntax/migration checks**

Run: `docker compose --env-file .env -f deploy/compose.yaml build api web`

Run: `docker compose --env-file .env -f deploy/compose.yaml run --rm migrate alembic upgrade head`

Expected: builds and migration command exit 0; this feature adds no schema migration.

- [ ] **Step 4: Perform controlled acceptance without retaining a test machine**

Use an authorized disposable SSH target or a target not already registered. Verify one wrong-password attempt leaves machine count unchanged, then one correct-password attempt creates exactly one machine and displays its summary. Archive the acceptance-only machine through the normal UI after recording evidence; do not delete existing resources or reuse production credentials in test fixtures.

- [ ] **Step 5: Verify deployed routes and health**

Deploy api/web using the existing Compose procedure, confirm `/health/ready` returns 200, `#/start` renders, refresh preserves it, and old `#/machines`, `#/clusters`, `#/functional`, and `#/performance` routes still load.

- [ ] **Step 6: Commit Task 4**

```bash
git add README.md docs/GUIDED_START_ACCEPTANCE.md
git commit -m "docs: add guided start acceptance"
```
