# Guided performance testing implementation plan

> Implement with test-driven development, isolated worktrees and independent review. User waived design questions/approval gates.

**Goal:** Make Start → Performance testing a usable DTT-backed guide with selectable tools, true measurement duration and total dataset size.

**Architecture:** Reuse platform performance options/preview/runs/report lifecycle; add a focused React guide and a backwards-compatible DTT timed workload contract.

**Tech stack:** React/TypeScript/Vitest/Playwright; FastAPI/Pydantic/Pytest; DTT Bash/Python and fio/elbencho.

**Spec:** `docs/superpowers/specs/2026-11-17-guided-performance-testing-design.md`.

## Global constraints

- No live cluster workloads, deployment or service restarts. No push or merge to shared branches.
- Keep finite-volume DTT jobs and existing performance page compatible.
- Runtime means per-tool per-round measured workload duration, not overall timeout.
- Preserve existing authorization, leases, cancellation and task-specific cleanup boundaries.
- Scope guide to fio/elbencho; mdtest remains on existing advanced page.
- Source edits use apply_patch. Worktrees may contain unrelated untracked caches/dependency symlinks; preserve them.

## Review focus

Check real CLI forwarding, native timed result validation, backend report identity, preview invalidation, stale async responses, data-size units, one-shot submission and compatibility with old DTT. Local-only test doubles must not replace the behavior under test.

### Task 1: DTT timed workload contract

Worktree `/tmp/dingofs-guided-functional.zMN5hR/dtt`, branch `feat/guided-performance-runtime` based on current local main. Files: DTT wrapper `dingofs-testsuite-tool`, `entrypoint.sh`, `scripts/performance_plan.py`, `performance_tools.py`, `performance_benchmark.py`, `performance_report.py`, corresponding tests and brief documentation.

- [ ] Add failing tests for `--runtime-seconds` forwarding, strict positive integer <=604800, legacy plan compatibility, finite preparation and timed measured commands.
- [ ] Add optional `runtime_seconds` plan field (omit or null for finite plans consistently); fio uses time_based/runtime, elbencho uses infloop/timelimit for measured data only. Expose runtime in `--dry-run` plan JSON so platform can detect old runtime support.
- [ ] Timed completion validates actual measurement and nonzero I/O, not exact finite bytes. Retain dataset validation and finite preparation checks; emit requested and measured duration separately from wall time and dataset/I/O bytes. Verify elbencho timer exit/report semantics using controlled tests and optional tiny local temporary native smoke; no cluster calls.
- [ ] Run focused tests RED/GREEN, full DTT pytest once, Bash syntax; report all failures. Commit only task files, no submodule pins or unrelated files. Write report with evidence.

### Task 2: Platform timed contract and runner integration

Files: `backend/src/dingofs_platform/performance/{schemas,commands,remote_runner,routes}.py` as needed; backend performance tests; `frontend/src/features/performance/types.ts` only for shared contract. Root owns this task.

- [ ] TDD optional runtime_seconds scalar/matrix validation, mdtest rejection, forwarding, preview normalized duration, snapshot and rerun persistence.
- [ ] Before timed workload run use DTT dry-run to check echoed runtime contract; unsupported old DTT yields actionable upgrade error without launching actual workload. Check report requested runtime agrees with request and required measurements are complete. Preserve finite jobs.
- [ ] Run performance suite against disposable test DB; no remote services. Record baseline and regressions.

### Task 3: Guided performance frontend

Files: new `frontend/src/features/getting-started/GuidedPerformanceFlow.tsx`, focused helpers/style and tests; `GettingStartedPage.tsx`, `App.tsx`; mocked browser spec. Shared types are produced by Task 2; do not overwrite parallel changes.

- [ ] Add failing tests for chooser routing, four-step flow, multi-tool selection, unit conversion, duration/data validation, machine/mount selection and stale preview invalidation.
- [ ] Implement spec flow, clear labels and consistent layout. Use `runtime_seconds` in API payload, a scalar per selected tool; normalize total_size bytes, allow backend derive file_count/file_size. Defaults per spec. Display total combined dataset and measured-time estimates. Timeout defaults must cover all rounds/tools plus preparation allowance; allow override with validation.
- [ ] Mount options come from `/performance/options`; machine change clears invalid mount. Directory mode supports manual mounts. Show machine name/IP/SSH user. Handle empty options, errors/retry, async stale responses and double clicks.
- [ ] Preview via `/performance/preview`; submit `/performance/runs`; navigate `#/performance/<id>` only on confirmed response. No background submit/retry. Include navigation away/dirty behavior consistent with existing guides. New entry starts a fresh form.
- [ ] Run focused RED/GREEN, full frontend suite, tsc/build, mocked browser exercise and screenshot for layout. Commit task files and write report.

### Task 4: Integration review and handoff

- [ ] Review per-task contracts and whole branch independently; fix important issues with regression tests.
- [ ] Run relevant combined suites and builds; document commands, passes, known failures and lack of live-cluster validation in a verification note.
- [ ] Leave coherent local commits/branches. Tell user what is implemented, how to reach it, and DTT upgrade requirement; do not claim deployed or live-tested.
