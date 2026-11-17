# Final timed preflight lifecycle fix

## Change

The DTT timed dry-run now runs in an owned process session with a bounded deadline and cancellation polling. Its process group is stopped and checked even when the wrapper leader exits before a child. The existing task-scoped Docker/Podman mount check runs during cleanup. A failed container listing, inspection, stop, or process-group confirmation produces remote `unknown`, so the manager does not treat the run as verified completion. Confirmed cancellation yields `cancelled`; confirmed timeout yields `failed`. The original JSON runtime echo check and finite path remain intact.

## Red / green evidence

- RED: `python3 /tmp/report-cache-tests-20261117.py tests/test_performance_runtime.py -q -k 'timed_probe_timeout or timed_probe_cancel'` — 3 failed as expected: preflight lacked owned cleanup arguments, and cancellation became `failed` after the old 30-second probe timeout.
- GREEN: `python3 /tmp/report-cache-tests-20261117.py tests/test_performance_runtime.py -q -k 'timed_probe_timeout or timed_probe_cancel or timed_dtt_probe_validates or old_dtt'` — 7 passed.
- RED mutation check: temporarily removed `CleanupUnconfirmed` state handling, then ran `python3 /tmp/report-cache-tests-20261117.py tests/test_performance_runtime.py -q -k unconfirmed_timed_probe_cleanup` — 1 failed (`failed` versus expected `unknown`). Restored handling.
- Final GREEN: `python3 /tmp/report-cache-tests-20261117.py tests/test_performance*.py -q` — 128 passed, 2 existing dependency deprecation warnings, exit 0. `git diff --check` — exit 0.

Four new test cases cover timeout with a persistent child while the leader stays or exits, cancellation during preflight with a real child, and unknown state when cleanup confirmation fails. The existing `test_performance_unknown_keeps_machine_lease` in `backend/tests/test_performance_api.py` asserts a machine lease remains held for `unknown`; `PerformanceManager.process` releases leases only for states outside `queued`, `running`, and `unknown`.

## Self review / limits

Only the remote runner and timed runtime tests changed. The child tests use real local processes, not Docker. Container stop remains scoped to containers whose mounts match both task data and output directories. A container runtime that cannot list or inspect containers now deliberately leaves state `unknown`; operator reconciliation is needed before lease release. No cluster, deployment, remote execution, or push was performed.
