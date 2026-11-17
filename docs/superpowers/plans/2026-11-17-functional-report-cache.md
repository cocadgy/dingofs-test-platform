# Functional Report Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make verified guided functional reports load locally without per-asset SSH or redaction.

**Architecture:** Fetch a bounded complete report once into a private atomic disk cache; keep per-request authorization. Prefetch when report completion is observed, lazily fill historical reports, and use private conditional responses with compression.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, Paramiko, pytest, PostgreSQL, Docker Compose, Nginx, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-functional-report-cache-design.md`

## Global Constraints

- No v2 report redaction or source archive validation on download.
- Preserve authentication, permissions, exact child/report binding and safe paths.
- No unrelated worktree changes, live test reruns or remote test resource deletion.
- Tests use only a disposable localhost database whose name ends in `_test`.
- Preserve original deployment image for rollback; no restart during active work.

## Review Focus

- Concurrent fills and API restarts must not publish partial reports.
- Authorization revocation must win over a warm cache and ETag match.
- Malformed remote trees must not write outside cache root or consume unbounded storage.
- Missing original source/archive must not block already generated report access.
- Prefetch errors must not turn successful tests into failures or hold DB locks during SSH.

### Task 1: Cached report delivery and prefetch

**Files:**
- Create: `backend/src/dingofs_platform/functional/report_cache.py`
- Modify: `backend/src/dingofs_platform/functional/reports.py`, `routes.py`, `manager.py`
- Modify: `backend/src/dingofs_platform/settings.py`
- Test: `backend/tests/test_functional_report_cache.py`, `test_functional_report_api.py`, prefetch tests

**Interfaces:**
- Preserve `download_report(db, actor, run_id, child_id, path) -> (bytes, media)` for routes.
- Add `prefetch_report(db, run_id, child_id)` using settings in `db.info`; manager calls it outside observation transaction and isolates cache errors.
- Settings `functional_report_cache_root: Path`, `functional_report_cache_max_bytes: int` default 2 GiB.
- Preserve existing `functional_report_transport(config, code)` injection; archive response shape documented by implementation tests.

- [x] Write failing tests for unchanged report bytes/no archive dependency and local reuse across different assets, permissions and conditional requests.
- [x] Run tests, confirm failures are the missing cache behavior.
- [x] Implement bounded remote bundle, atomic private local cache, lock/eviction, route ETag and prefetch.
- [x] Add and run adversarial/failure/concurrency and prefetch regression tests.
- [x] Run full backend suite and review changes; commit only this task's files. Existing baseline failures independently reproduced; see evidence notes.

### Task 2: Deployment and real-browser verification

**Files:** `deploy/compose.yaml`, `deploy/nginx.conf` (actual config located during audit), `.env.example`, design evidence notes.

**Interfaces:** Persist task 1's cache root in a dedicated volume. Nginx gzip selected report media; no public report alias or proxy cache.

- [x] Configure volume/settings and gzip; verify effective compose and Nginx syntax without exposing secrets.
- [x] Build API from reviewed development worktree, compare to running release; retain prior image.
- [x] Run full backend suite against disposable database; inspect active jobs before replacing API.
- [x] Deploy targeted API/config update only; do not restart DB or run migrations.
- [x] Repeat same URL in Chromium cold/warm and check all assets, summary, auth and ETag.
- [x] Record before/after timing and any limitations in evidence notes.

Evidence: `docs/superpowers/specs/2026-11-17-functional-report-cache-evidence.md`.
