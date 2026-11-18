# MLPerf live fixes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Track completed steps with checkboxes.

**Goal:** Make short MLPerf guide runs valid and their embedded reports accessible.
**Architecture:** Scoped native-report compatibility, matching frontend/backend/DTT dataset minima, and existing proxy report exception.
**Tech Stack:** Python, pytest, TypeScript/React, Vitest, Nginx, Chromium.
**Spec:** `docs/superpowers/specs/2026-11-18-mlperf-live-fixes-design.md`.

## Global Constraints

- Keep MLPerf v2.0 image and native training parameters except dataset normalization.
- Do not turn absent or invalid required metrics into zero or successful results.
- Preserve raw native reports and historical task states.
- CosmoFlow minimum is four files per accelerator AND three complete batches; file counts remain divisible by accelerator count.
- Keep unrelated dirty submodule/node_modules/bytecode untouched. No main merge or push.
- Use apply_patch for edits. Only root deploys and submits real workloads.

## Review Focus

- Optional checkpoint NaN versus required training NaN/Infinity: Task 1.
- Other malformed metadata, missing reports, incomplete epochs: Task 1.
- One and multiple accelerators; explicit insufficient count versus derived count: Tasks 1 and 2.
- Report paths must be embeddable without permitting generic API/page embedding: Task 2.
- Existing fio/elbencho report headers and other model minimums must not change: Task 2.

### Task 1: DTT native report and small-dataset compatibility

**Worktree:** `/tmp/dingofs-guided-functional.zMN5hR/dtt` (base `ece1c41`).
**Files:** `scripts/mlperf_benchmark.py`, `tests/test_mlperf_benchmark.py`.
**Interfaces:** Keep `dtt-mlperf-v1`, `build_plan(args)` and native summary contract. Platform uses the identical minimum from Task 2.

- [ ] Add RED tests for UNet3D native summary with four NaN fields:
  `save_checkpoint_io_mean_GB_per_second`, `save_checkpoint_io_stdev_GB_per_second`,
  `save_checkpoint_duration_mean_seconds`, `save_checkpoint_duration_stdev_seconds`.
  These optional absent stats must not invalidate valid training. Preserve raw attachments.
- [ ] Keep/add tests rejecting NaN/Infinity in required metrics, invalid metadata,
  missing summaries/epochs, and invalid measured duration. Add explicit 3-file
  rejection and 4-file acceptance for one Cosmo accelerator, 6 rejection/8 acceptance
  for two. Update obsolete three-file positive fixtures to four-file native constraints.
- [ ] Run failing tests, record relevant RED output; implement narrowly scoped native
  optional-stat handling and minimum. No broad raw JSON relaxation or invented metrics.
- [ ] Verify focused tests and real saved UNet report parsing using temp output only.
  Evidence is under `/home/jenkins/.local/share/dingofs-platform/performance/8fb1d9bb-1206-4d8e-abd0-08e9e4c2c08e/output/scene-001-mlperf/performance-mlperf-20261118T045703Z-a7788bc00b9b`.
- [ ] Run full DTT suite once: `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PYTHONPATH=. python3 -m pytest -q tests`.
  Persist test logs and report failing names if any. Commit only owned files.

### Task 2: Platform minimum and report proxy

**Worktree:** `/tmp/dingofs-guided-functional.zMN5hR/platform` (code base `aed3798`).
**Files:** backend `performance/schemas.py`, `tests/test_performance_mlperf.py`;
frontend `features/getting-started/guidedPerformanceModel.ts`, `GuidedPerformanceFlow.tsx`
and their tests; `deploy/nginx.conf`, `deploy/tests/test_nginx_proxy.py` (or focused sibling).
**Interfaces:** Match Task 1 normalization: Cosmo 1 MiB -> 4 files/11,313,944 bytes;
two accelerators -> 8 files/22,627,888 bytes. Native reports retain `scene-N-mlperf` routes.

- [ ] Add RED backend/frontend cases deriving four/eight files, rejecting explicit
  three/six counts, accepting four/eight, unchanged other model minima. Explain reader
  requirement in existing size hint so UI does not imply three files suffice.
- [ ] Add RED effective Nginx response test with upstream stub for plain `mlperf`
  and `scene-001-mlperf`: HTML 200 and API frame-ancestors self policy survives,
  no DENY/global frame-ancestors none; generic API retains restrictions. Preserve fio/elbencho.
  Test behavior, not substring presence. Reuse existing isolated Nginx fixture.
- [ ] Implement minimum and scoped MLPerf proxy alternative; no unrelated mdtest expansion.
- [ ] Run focused frontend, backend and proxy tests; frontend build. Root owns full
  backend suite to avoid shared isolated DB concurrency. Agent runs frontend full suite once.
  Existing unrelated failures must be reported by name, not silently omitted.
- [ ] Commit only owned code/tests; leave root design/plan files to root.

### Task 3: Integration, deployment and browser acceptance (root)

- [ ] Review both tasks and cross-component values, run all performance backend tests
  and complete isolated backend suite once, retaining failure list (baseline is not green).
- [ ] Fresh final review, then version the isolated performance DTT bundle, preserving
  functional `tools/dtt/current` and prior bundle/image rollback targets.
- [ ] Build API/web images, verify no active platform workloads, switch only API/web
  via existing release Compose wrapper and wait for API health.
- [ ] Browser guide: one epoch, one accelerator, one generator, one round, requested
  1 MiB for ResNet50, UNet3D, CosmoFlow sequentially; enable success data cleanup.
- [ ] Check native metrics/epochs, all report frames, data cleanup, original failed
  task evidence unchanged; record exact IDs and verification results.
