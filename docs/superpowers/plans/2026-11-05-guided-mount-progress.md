# SDD ledger — plan: docs/superpowers/plans/2026-11-05-guided-mount.md

Spec approved; inline execution approved. Base: 609f995.

Pre-flight: tasks 1/2 expose mount.plan and mount.create(plan_id/retry_operation_id); tasks 3/4 consume these. Existing single-machine mount.create remains unchanged for legacy requests.

Ruling: work in the existing branch and publish a HEAD-plus-selected-patches snapshot, consistent with the user's prior no-new-worktree instruction. Unrelated dirty files are preserved; partial staging is required for shared frontend files.

Tasks 1–4: implemented. Backend plan schema, per-client identities, pinned client binaries and ports, immutable plan consumption and retry validation; four-step multi-machine wizard, templates and subflows.

Task 5 verification: 44 focused backend tests passed in an isolated PostgreSQL database. Frontend type checking and Vite production build passed with Node 22. No real clients mounted or unmounted. Existing unrelated resource UI test failures remain outside this change.

Final reviewer findings addressed: private state initialization precedes log directory creation; unresolved launcher state cannot relaunch; explicit binary sources cannot fall back silently; checked ports are retained and revalidated. Four regression cases failed before fixes and passed afterwards. Default local cache paths are isolated per client.

Release: selected staged patch snapshot only, preserving unrelated worktree changes. Deployment health and UI checks are performed after image build; runtime SSH mounting remains for manual user validation.
