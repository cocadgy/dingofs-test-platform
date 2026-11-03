# Guided cache settings implementation and verification
User-approved scope: capacity MiB/GiB/TiB selectors preserving actual capacity; sudo fallback only for missing cache bases; full catalog, common expanded/others collapsed; load template and save as new template without overwriting.
Execution: current session sequential, approved by user "开始".
Base: 746cf76. Preserve all unrelated functional/performance/resource workspace changes.
Tasks:
- CapacityInput, guided model/flow, unit tests.
- Narrow cache_directory helper, remote packaging, ownership/path tests.
- GuidedCacheParameters, reusable editor folding, template and request integration tests.
- Review scoped diff, build isolated snapshot, commit/deploy.
Ruling: cache catalog stays version-labeled, not queried dynamically per TAG; user's approved scope is the platform catalog.
Ruling: sudo is noninteractive and requires authorization for the execution user, not the SSH login user. Failure remains actionable; no global sudoers edits.
Ruling: new missing intermediate directories are created 0755 subject to umask; existing ancestors unchanged. Unsearchable existing ancestors fail closed because missing vs existing target cannot safely be inferred.
Verification so far: frontend guided/cache profiles 48 passed; directory 5 passed. Additional ownership/concurrency and payload tests pending.

Final review: independent reviewer found protected-staging race and search-only ancestor compatibility; both reproduced RED then fixed GREEN.
Minor deferred: confirmation shows original template/default label, not a separate override badge. Edited values still submit correctly; full parameter editor shows them.
Ruling: no protected same-filesystem staging ancestor => fail closed with administrator guidance, rather than weaken race protection.
Verification: guided/template frontend 50 passed. Root container directory checks 11 passed; nonroot 10 passed, 2 root-only skips (search-only test passed). Full frontend 451 passed / 7 existing failures; full backend 741 passed / 20 existing failures, 2 existing errors, 1 root-only skip before final review additions. Failure lists match previous baseline logs.
