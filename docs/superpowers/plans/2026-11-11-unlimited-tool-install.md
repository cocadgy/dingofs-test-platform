# Single-install unlimited duration

> Execution: current session, using executing-plans. User approved proceeding without intermediate questions.

Goal: Retry automatic DTT installation without a total duration deadline.
Design: Add a strict boolean `no_timeout` to automatic-install requests only; persist it in task options. Keep default behavior unchanged, preserve connection/idle failure detection and exclusive leases. No arbitrary large timeout substitutes. Expose a null deadline for unlimited tasks without changing the existing database schema. Internal legacy deadline is ignored only for these explicitly opted-in tasks.
Alternatives: Raising the global limit is not unlimited and affects other jobs; bypassing the installer would lose audit and locking. Use a scoped API option instead.

## Task 1: implementation and verification
- [x] Add failing tests for unlimited request validation, expired unlimited jobs, transport deadline propagation, and real helper transfers without a deadline.
- [x] Modify routes.py, service.py, automatic.py, ssh_session.py and scp_helper.py to implement the option; don't fall back from a deployment timeout to SFTP.
- [x] Run targeted tests then backend suite and independent scoped review.

## Task 2: deploy and retry
- [ ] Build an immutable API image from reviewed sources and restart API only; verify readiness.
- [ ] Verify the failed task's remote worker has ended, reconcile only its leases with evidence. Never release unrelated leases or delete unknown staging data.
- [ ] Submit one auto_install request with no_timeout=true and monitor the actual outcome. Keep connection failures visible.

Review focus: defaults remain bounded; malformed boolean rejected; failed jobs keep leases; no Infinity serialized into SSH input; unlimited tasks don't expire on polling. Unit operation timeouts (e.g. connection establishment) remain distinct from the removed total installation limit.

Progress: targeted installer tests initially 28 passed. Independent review identified non-reply-based Paramiko keepalive; replaced it with an SSH request/reply probe bounded independently to 30 seconds, plus TCP failure detection, with responsive and nonresponsive regression tests (RED then GREEN). Full backend suite running; baseline asset permission failures reproduced without any patch in a separate database. No unrelated fixes are included. Existing failed-job files will be retained, not deleted, and only the verified finished owner's lease may be released.

Final validation: final scoped installer/lease suite 57 passed. Whole backend run: 1131 passed, 224 skipped, 31 failed and 2 teardown errors; all 31 failed cases and both errors reproduced on unchanged HEAD in a separate baseline database. They belong to asset permissions, cluster operations, functional preflight/scheduler, host trust, credentials, remote integration/security, resource batch and resource command tests. No claim of a green whole suite. Full outputs retained locally under /tmp/dtt-unlimited-*.log. Review issue resolved by request/reply watchdog tests. This change does not fix pre-existing suite failures.
