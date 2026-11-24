# Review Remediation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development; execute the three repository tasks in order with a different reviewer after each. No commits or deployment in this task.

**Goal:** Fix the 13 findings from the November 24 code reviews and independently verify each repository.
**Architecture:** Preserve current guided/ordinary entry points. Make cancellation and deadlines durable, preserve actual tool outcomes, and tie cleanup and assertions to explicit evidence rather than inference.
**Tech Stack:** Python, Bash, FastAPI, SQLAlchemy, pytest.
**Spec:** User-approved review findings in this conversation: platform 3, DTT 3, integration 7; user requests sequential fixes and another agent to verify.

## Global Constraints
- Work only in the existing feature workspaces under /tmp/dingofs-guided-functional.zMN5hR.
- Do not modify the separate integration main checkout, deploy, commit, push, or contact live clusters.
- Preserve unrelated deletions, generated files and existing user edits.
- Tests use isolated directories, subprocess doubles and the dedicated test database only, never production resources.
- Each finding requires a failing behavioral test before implementation and fresh passing evidence afterward.
- Reviewers must be different agents from implementers and must validate behavior independently.

## Review Focus
- Cancellation racing bootstrap and actual workload launch must not allow a new launch after acknowledged zero-start cancellation.
- Remote timeout must work without API polling and retain cleanup/recovery evidence rather than killing arbitrary processes.
- Active and unknown task leases must protect machine connection identity, including concurrent launch/update.
- Failure, timeout, missing quota output and cancellation must not become success; commands must target the selected environment regardless of option order.
- Ordinary cleanup must not remove another run's similarly named filesystem, cache member or mounts, and must not recursively remove an uncertain mount.

### Task 1: Platform lifecycle and inventory

Repository: /tmp/dingofs-guided-functional.zMN5hR/platform, baseline 8749d0b.
Files: backend/src/dingofs_platform/functional/{remote_runner,scheduler,manager}.py; backend/src/dingofs_platform/inventory/routes.py and existing lease helpers as needed; backend/tests/test_functional_guided_transport.py and focused scheduler/inventory tests.
Interfaces: bootstrap_child(request, source, event_source), snapshot_child(request, cursor, cancel), run_child(root, request), scheduler._payload, inventory PATCH and existing OperationLease.
- [x] Reproduce missing-request cancellation followed by delayed bootstrap; add tests for both orderings and mismatched identity. Persist cancel under the bootstrap lock, bind child/token, and prevent acknowledged zero-start work from launching. Preserve readonly missing polling.
- [x] Reproduce remote running past a configured timeout without API polls. Freeze timeout_minutes into the launch request and enforce locally with graceful cancellation; retain a durable timeout reason and existing resource recovery. Test no-timeout/backward compatible requests, normal completion, deadline and API-observed terminal attribution.
- [x] Reproduce connection identity edits while machine/runtime leases are held. Reject actual address/ssh_port/ssh_user changes with 409 while preserving edits to name/tags/credentials and allowing changes after lease release. Use existing locking convention to avoid edit/start races and test it.
- [x] Run focused tests and complete backend suite against dedicated test DB. Report baseline failures by name; do not repair unrelated tests. Self-review and write task-1-report.md with RED/GREEN commands, files, limitations.
- [x] Fresh agent validates all three findings and regression boundaries before task 2.

### Task 2: DTT exit status, installation and environment routing

Repository: /tmp/dingofs-guided-functional.zMN5hR/dtt, baseline e1604b6.
Files: entrypoint.sh, install.sh, dingofs-testsuite-tool, tests/test_mlperf_benchmark.py and focused shell/runtime regression tests.
Interfaces: fio_run / LTP entrypoint status, installer output layout, MLPerf benchmark CLI.
- [x] Run fake fio/runltp through real functions with exits 0/7/124 and assert recorded/final status. Save producer PIPESTATUS in its own shell and preserve reporting under errexit, including tee failures; fix both legacy paths.
- [x] Test actual installer with offline fixture downloads and temporary installation prefix. Install required MLPerf adapters at the wrapper's supported lookup location; test training/checkpoint/kvcache plan generation from installed artifacts, not hand-copied adapters.
- [x] Test --setup-env before/after -t for MLPerf benchmark. Perform selected setup before command planning/mount selection, refresh testdir, stop on setup failure. Preserve dry-run semantics (no real setup side effects) explicitly.
- [x] Run focused tests, full offline unit suite, shell syntax checks; document existing failures and task-2-report.md.
- [x] Fresh agent validates all three findings and compatibility before task 3.

### Task 3: Integration ownership, assertions and reporting

Repository: /tmp/dingofs-guided-functional.zMN5hR/dtt/dingofs-integration-test, baseline 801459f. Do not change /home/jenkins/dgy/github/dingofs-integration-test (main).
Files: src/config/{env_setup,env_cleanup}.py, run_tests.py, src/quota_test/executor.py, src/test_runner/{allure_reporter,report_generator,test_suite}.py; focused offline tests.
Interfaces: ordinary setup/cleanup resource handoff, mount_clients/verify_unmount, _step_get_fs_quota/_step_create_file_fail, suite result and Allure JSON.
- [x] Verify and test ordinary cleanup cannot select test-production for a test run. Carry exact created resource identities through ordinary setup/cleanup; handle standalone cleanup explicitly without guessing ownership from prefixes. Preserve guided OwnedResources path. Cover filesystems, cache members and mount targets and setup partial failure cleanup.
- [x] Test failed unmount/query and disconnected/missing mount. Use exact mount table evidence; unknown queries fail closed. Never recursively delete an uncertain mount; remove only confirmed empty mount directory. No actual mount/delete in tests.
- [x] Test all required mount attempts fail: setup raises and cases never run on underlying directory. Keep successful mount flow and owned cleanup compatibility.
- [x] Test quota verify mismatch, missing output/unknown keys and valid fields. Parse actual table/JSON fixtures already in project; enforce YAML USED/IUSED and any supported fields. Bounded polling only where existing async quota semantics need it.
- [x] Test expected quota denial versus permission denied, missing dd, disconnected endpoint and a successful write followed by failed ls. Only explicit EDQUOT/verified quota denial passes; enforce applicable verify.result.
- [x] Give repeated Allure attempts stable module+case-path identity and attempt/final metadata. Fallback summary must count the final attempt once, retain history, and avoid collisions between same basename in different modules or runs. Test fail/pass, final fail and no retries; do not claim real Allure CLI rendering without checking it.
- [x] Ordinary CLI cancellation/incomplete execution returns nonzero (cancel=130); no-case cancellation cannot pass. Keep guided terminal behavior.
- [x] Run focused tests and full offline suite after inspecting collection for live tests. Document exact exclusions/failures and task-3-report.md.
- [x] Fresh agent validates seven findings and cross-repository contracts; final controller checks diffs, test evidence and unresolved findings.
