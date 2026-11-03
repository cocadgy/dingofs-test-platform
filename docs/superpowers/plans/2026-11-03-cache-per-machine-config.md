# Per-machine cache configuration
Approved: each machine owns its parameters/template; global group name/suffix and binary source/TAG only. Path-mode binary directory belongs to each machine. New machines clone first current cache settings, not identity/user/binary path; RDMA pair validated per target. No ongoing sync.
Architecture: row-owned options/profile revision, typed member controls canonicalized once; backend materializes complete per-member snapshots, retains legacy global requests. Explicit empty options replace template rather than merge. No shared mutable options. Detaching template preserves values.
Tasks: tests first for isolation/template detach/clone/paths/backend snapshots; backend member options + profile resolution; machine card + copy + confirmation; migrate legacy drafts once after profile metadata loaded; focused checks, independent review, isolated builds, commit/deploy.
Non-goals: live mutation of existing cache groups; querying flags dynamically for every TAG.
Review focus: empty options vs absent; stale templates fail before execution; clone excludes addresses/users/path; first-machine changes do not propagate backwards; exact options survive plan consumption/retry; cancel template association keeps values.

## Execution record
- Model tests observed RED, then GREEN: independent snapshots, template detach, cloning exclusions, per-machine paths, one-time legacy migration; template node IDs excluded from expanded submissions.
- Backend tests observed RED, then GREEN: per-member options/profile resolution, explicit empty options, expiry, create snapshots, stale template rejection, revision pair validation.
- Frontend interaction checks: per-machine capacity/weight, path-mode mandatory directories, new-machine inheritance, copy selection/confirmation, full guided flow.
- Isolated build from staged tree only; unrelated working-tree changes excluded.
- Full backend: 750 passed, 20 failed, 2 skipped, 2 errors. Failure/error names match pre-change baseline exactly.
- Initial full frontend: 466 passed, 7 failed. Failure names match pre-change baseline exactly.
- Final review: independent read-only reviewer found two important compatibility cases. Fixed legacy catalogue defaults inserting member {}, and unavailable-template selection that prevented detaching. Both reproduced by failing tests before fixes.
- Final: minor (deferred): confirmation uses generic prepare/distribute wording even for existing-path mode; step 2 and per-machine input explicitly state no download/distribution, and execution correctly uses target-existing binaries.
- Final: Ruling: reviewer excluded unrelated unstaged code/baseline failures — preserve unrelated work and require no new failures in this scope — those separate existing issues remain.
- Final: Ruling: remote binary execution reviewed statically, not exercised against real cache nodes — avoid creating services merely to validate UI — real machine-specific executable/permission failures remain checked by the existing preparation operation.

- Final verification: both review regressions RED→GREEN; focused backend 18 passed. Final frontend 468 passed / 7 existing baseline failures; exact failure-name comparison unchanged. Backend product code unchanged after its full run. Web/API image builds successful.
