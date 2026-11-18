# Guided MLPerf Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. User delegated decisions and waived further questions. Steps use checkbox syntax.

**Goal:** Add honest DTT-backed MLPerf Storage training support to the performance guide.

**Architecture:** A separate DTT MLPerf adapter preserves the legacy entry, a typed platform contract normalizes training datasets and validates native reports, and the existing four-step guide renders tool-specific controls.

**Tech Stack:** Bash/Python DTT; FastAPI/Pydantic; React/TypeScript/Vitest/Playwright.

**Spec:** `docs/superpowers/specs/2026-11-18-guided-mlperf-design.md`.

## Global Constraints

- No live cluster workloads, deployment, service restart, push or main merge.
- Reuse linked worktrees: platform `/tmp/dingofs-guided-functional.zMN5hR/platform`, DTT `/tmp/dingofs-guided-functional.zMN5hR/dtt`. Preserve existing node_modules link, caches and DTT submodule changes.
- MLPerf is v2.0 training only: resnet50/unet3d/cosmoflow. No false official compliance or timeout-as-measurement claims.
- Reuse existing cancellation, scoped directories and unknown-on-unconfirmed-stop. All production edits follow failing-test evidence and apply_patch.
- Independently owned backend, frontend and DTT files may run in parallel under the developer's parallel-work direction; root coordinates the fixed shared contract.

## Review Focus

- Old DTT or non-JSON dry run must not silently launch an unsupported workload (Task 2).
- Byte requests rounded to complete model files must be explained, bounded and identical across front/backend/DTT (Tasks 1–3).
- Exit 0 with absent/stale/partial native metrics is not success; one failed round fails the run (Tasks 1–2).
- MLPerf-only form must not validate hidden fio fields or imply fixed measurement duration; mixed selections must serialize distinct parameters (Task 3).
- No required TTY and no hard-coded /data escape from per-task target; preflight side effects, cancellation and failure must be checked (Tasks 1–2).

### Task 1: DTT MLPerf adapter

**Files:** New `scripts/mlperf_benchmark.py`, `tests/test_mlperf_benchmark.py`; modify `dingofs-testsuite-tool`, `entrypoint.sh`, necessary shell integration tests and README. Keep new native parsing/execution focused; existing large shell scripts get only routing/forwarding. Do not change legacy MLPerf scenarios or submodules.

**Interfaces:** Consume the command and output contract in the spec verbatim. Produce `dtt-mlperf-v1` dry-run and summary, `performance-mlperf-*/summary.json`. Model metadata and file-count validation use spec constants. `--file-count` is required in this new entry; default model=resnet50/epochs=5/accelerators=1/concurrency=4/rounds=1. Optional `DTT_MLPSTORAGE_BIN` permits isolated test CLI; real default is mlpstorage.

- [x] Write failing tests: real adapter dry run is pure JSON with no filesystem/CLI effects; wrapper and entrypoint forward all fields without TTY; invalid model/epochs/count/runtime rejected; zero/missing/nonfinite native metrics and failed round fail.
- [x] Implement the new adapter, using verified fixed upstream native schema for metrics and proving completed epochs where available. Each measured round has distinct output, raw JSON evidence and strict expected model/parameters. Report failed partial execution with logs; no broad cleanup. Communicate the precise native schema and parser assumptions to root before finalizing.
- [x] Add wrapper/entrypoint routing for `mlperf -s benchmark` and flag recognition. Do not let generic fio parsing consume these options or old mlperf ignore them. Dry-run works before container availability checks and produces only JSON.
- [x] Run new focused tests, existing performance tests, shell syntax and full pytest once; report every non-pass. Commit only task files and return report plus SHA.

### Task 2: Platform MLPerf contract and runner

**Files:** `backend/src/dingofs_platform/performance/{schemas,commands,routes,remote_runner}.py`; new `backend/tests/test_performance_mlperf.py`, relevant existing tests. Root owns this task. Frontend shared types belong to Task 3.

**Interfaces:** Consume Task 1 dry-run/summary. Add TestSpec/ParameterMatrix MLPerf fields, normalize as spec. Commands pass explicit file count and MLPerf controls, never runtime/io/block flags. Options tools includes mlperf; allow all four tool definitions in API, preserving max256 scenarios.

- [x] RED tests for literal file-count derivation (resnet 1GiB→8 files/1147517984 estimated bytes), minimum batches, count alignment, invalid runtime/model/fields, scalar and matrix expansion, CLI forwarding, options/preview/rerun.
- [x] Implement schema/command/routes. Do not multiply irrelevant model defaults into existing tool matrices; non-MLPerf parameter validation stays compatible.
- [x] RED tests for new DTT probe guard, missing/mismatched plans, false-success native rounds, corrupted metric structures and report collection; then implement using tracked probe lifecycle and native summary validation.
- [x] Run isolated backend performance suite, full suite once and local contract smoke through real platform runner + real DTT adapter with strict fake external MLPerf CLI. No cluster calls. Commit task files and write evidence.

### Task 3: Guide and report UI

**Files:** `frontend/src/features/getting-started/{GuidedPerformanceFlow.tsx,guidedPerformanceModel.ts,guided-performance.css}`; `frontend/src/features/performance/{types.ts,PerformancePage.tsx}` and existing helper/report component files as necessary; focused frontend tests and `frontend/tests/guided-performance.spec.ts`.

**Interfaces:** Extend Tool with mlperf; Spec fields `mlperf_model`, `mlperf_epochs`, `mlperf_accelerators` optional. Default form MLPerf values per spec. Payload MLPerf item passes tool/model/epochs/accelerators/concurrency/total_size/rounds only (no runtime or fio controls). Common measurement estimate counts fio/elbencho only and explicitly excludes MLPerf's unknown duration. Combined estimated bytes includes rounded MLPerf nominal dataset. Backend preview remains authoritative.

- [x] RED tests for choosing MLPerf, training-specific values, model dataset rounding, no runtime/io flags, mixed tools, hiding/ignoring irrelevant fields, preview invalidation and genuine single submit.
- [x] Add MLPerf selection and conditional controls/labels. Only MLPerf selected shows epochs/rounds/total timeout; mixed selection labels fio/elbencho duration separately. Display internal/non-compliant and approximate-data notes. Do not add arbitrary model strings.
- [x] Extend report rendering to show samples/s, accelerator utilization %, and only real measurement if supplied; requested runtime absent does not render bogus 0 seconds. Preserve native JSON/HTML links and rerun display. Advanced page need not add an MLPerf editor, but shared Tool widening must not break its records/guards; link MLPerf users to the guide if appropriate.
- [x] Run focused/full frontend tests, tsc/build and mocked browser walkthrough with MLPerf-only and mixed payload. No live API. Commit only owned frontend files and write evidence.

### Task 4: Reviews and handoff

- [x] Per-task spec/quality reviews and fixes; one final cross-repository review. Its sole Important finding (native three-batch minimum) was corrected in one cross-repository fix wave and approved by one scoped re-review; two nonblocking follow-ups documented.
- [x] Close installation integration gap found during review: include optional MLPerf adapter in automatic/packaged DTT source transfer; support installed flat runtime layout during dry-run; test actual installed-wrapper preflight without a container/cluster workload.
- [x] Verify shared contract with local-only runner smoke, relevant suites/build; document known full-suite non-passes and no real MLPerf/cluster execution.
- [x] Commit verification note and completed plan. Preserve feature branches and user changes, no deploy/push/merge; report support and actual limits without asking questions.
