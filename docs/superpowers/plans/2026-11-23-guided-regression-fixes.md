# Guided regression fixes implementation plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task; retain existing isolated worktree.

**Goal:** Remove three observed blockers and repeat affected guided browser workflows on 126.
**Architecture:** Keep existing resource, preflight and durable performance-job boundaries. Fix external-member compatibility, scope identity checks, and distinguish verified non-launch from ambiguous execution. Do not delete unrelated resources or bypass required environment prerequisites.
**Tech Stack:** Python, FastAPI, PostgreSQL, pytest, React, Playwright.
**Spec:** User-approved repair of the three issues reported in the November 23 guided regression; previous instruction requests continuous implementation and verification without intermediate questions.

## Global constraints
- Preserve external resources, old mounts/processes, and unrelated worktree changes.
- Never relaunch an ambiguous performance job automatically.
- Only release task leases after non-launch or terminal completion is verified.
- Validate through real browser flows, using small isolated 126 test resources.

## Review focus
- External cache members lacking machine_id still reserve a matching address/port.
- Unrelated deleted-binary processes do not block an isolated run; relevant identity remains checked.
- SSH failures before command dispatch are terminal without leaking leases.
- A delayed bootstrap cannot launch after missing-task cancellation is acknowledged.
- Missing directory, tool and runtime capabilities remain explicit failures rather than being silently ignored.

### Task 1: External cache port reservations
Files: backend/src/dingofs_platform/resources/port_planning.py; backend/tests/test_cache_ports.py.
Interface: reserved_ports(db, member) -> set[int], consumed by reserve and store_effective_port.
- [ ] Add regression tests for missing machine_id, matching listen IP, unrelated host, malformed port and self-member.
- [ ] Run tests and observe current KeyError.
- [ ] Match registered identity or known address without fabricating external ownership; validate reservable ports.
- [ ] Run cache/resource tests, inspect diff.

### Task 2: Functional preflight scope and usable environment
Files: backend/src/dingofs_platform/functional/preflight.py; backend/tests/test_functional_preflight.py.
Interface: READ_ONLY_PROBE preserves checks and fingerprint response.
- [ ] Trace selected-module requirements and actual runtime capabilities.
- [ ] Add executable probe regression for an unrelated stale executable and relevant invalid identity.
- [ ] Run RED, scope process identity inspection to required mount paths, run GREEN.
- [ ] Retain genuine prerequisite failures; select/configure valid isolated test environment via supported workflow.

### Task 3: Performance launch and cancellation recovery
Files: backend/src/dingofs_platform/performance/{transport,manager}.py; backend/tests/test_performance_api.py; new backend/tests/test_performance_transport.py.
Interface: Transport.start, Transport.poll; explicit pre-dispatch failure, durable cancellation fence for absent jobs.
- [ ] Test connection-constructor failure releases leases but post-dispatch failure keeps unknown.
- [ ] Test cancel of missing job writes a launch fence; delayed bootstrap observes it and never starts workload.
- [ ] Observe RED, implement smallest lifecycle change, observe GREEN.
- [ ] Verify missing-without-cancel remains unknown and never relaunches.

### Task 4: Verification and browser regression
- [ ] Run complete backend and frontend suites; report baseline failures separately.
- [ ] Fresh-context review of fixes; address significant findings with failing tests first.
- [ ] Deploy only relevant platform service changes, recover own cancelled job through supported state machine.
- [ ] Browser cache creation, functional basic case, checkpoint read/write-read, cancellation and report checks.
- [ ] Report actual task IDs, outcomes, remaining untested hardware-dependent branches; do not merge or push without request.

## Execution evidence (2026-11-23)

Three fixes implemented and deployed to the API only. Independent review's malformed-IP finding reproduced and fixed; extra concurrency/dispatch coverage suggestions deferred (existing lock ordering reviewed, sequential cancellation and ambiguity tests present).

Real browser checks passed: cache creation on 126; one basic_file_operation case with full preflight/cleanup/Allure; MLPerf checkpoint read and write-read including native reports. The previous unknown performance run became cancelled and released all leases through normal recovery. The original incomplete smoke profile remains correctly rejected; retest used complete env_126_dirstat without caches. Multi-machine execution, RDMA/GPU hardware and every binary-source combination were not newly exercised.

Full-suite results are not all green: backend 1531 passed / 31 failed / 9 skipped / 2 errors; all failed/error nodes reproduced on unmodified HEAD. Frontend 585 passed / 7 failed, with no frontend source changes. Exact test names and traces are in /tmp/guided-fixes-full-backend-20261123.log and /tmp/guided-fixes-full-frontend-20261123.log. Browser evidence: /tmp/guided-fixes-web-evidence-20261123.json. No commit/push/merge in this repair.
