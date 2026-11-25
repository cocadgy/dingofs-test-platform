# Guided validation fixes

## Scope and design

Repair the five findings from the November 25 web validation. Keep preflight read-only and fail closed; do not hide missing environment prerequisites or fabricate benchmark success. No deployment, push, or unrelated worktree changes. Existing user instruction permits continuous implementation without intermediate design questions.

## Tasks

- [ ] Platform preflight: add regression tests for missing-directory reasons, Python capability reasons, skipped checks and environment/module attribution; implement bounded diagnostic fields and render them in PreflightStep. Preserve boolean checks and token binding.
- [ ] Integration descriptors: include configured remote cache data/log roots, with a regression test using remote_cache_conf.
- [ ] DTT summary: test real shell summary block against guided lifecycle output and legacy output. Count final case outcomes, do not let successful case counts override nonzero process exit; unknown counts are not zero failures.
- [ ] MLPerf: test zero-request native output separately from malformed metrics; report the model/duration and absence of effective samples without asserting an unproved root cause.
- [ ] Allure: test report metadata with misleading hostname DNS; derive local address from route to MDS rather than public hostname DNS, omit unverifiable IP.
- [ ] Run affected and full local suites, frontend build; fresh review of changes. Record environmental failures separately. No real cluster workload necessary for error parsing tests.

## Review focus

Missing/invalid diagnostic data must not allow execution; same-host multiple profiles need attribution; skipped checks cannot mask false checks; zero/invalid KV values remain failures; nonzero exit after passing cases remains failure.

## Decisions and evidence

Initial evidence: /tmp/guided-web-recheck-20261125.knhZ0K/functional-preflight-audit.json.
Existing worktrees contain unrelated deleted files; leave untouched.
Quota profile repair requires source/runtime-consistent interpreter selection and explicit configuration preparation; do not silently switch only the probe interpreter or mutate shared environment during a read-only preflight.

## Progress ledger

- Preflight diagnostic regressions reproduced then fixed; 65 tests passed with dedicated PostgreSQL and the verified integration source.
- Frontend skipped status regression reproduced then fixed; production TypeScript/Vite build passed. Full suite: 586 passed, 7 failed; the same 7 failures reproduce on an unmodified HEAD export.
- Allure address and remote cache descriptor regressions reproduced then fixed; 45 tests passed.
- DTT summary and MLPerf regressions reproduced then fixed; targeted 46 passed. Real November 25 quota/basic event replay yields `1 1 0 SUCCESS`; nonzero exit yields `1 1 0 FAIL`.
- Independent reviewer found missing runtime delivery for integration_summary.py. Added failing automatic-export, CLI mount and offline-manifest tests; fixed all three delivery paths. Packaging tests: 21 passed, 5 skipped (optional external source fixtures).
- DTT full suite after delivery fix: 330 passed, 2 skipped, 257 subtests. Initial two localhost HTTP failures disappeared with proxy variables unset.
- Ruling: keep pre-existing deleted files and unrelated test failures untouched; report separately. No shared quota environment mutations, deployment, commits or push in this task.
- Final verification: platform targeted 87 passed/5 skipped; frontend targeted 11 passed and production build passed; integration targeted 92 passed; DTT full final 335 passed/2 skipped/257 subtests.
- Full backend 31 failures/2 errors and frontend 7 failures reproduced on unmodified HEAD. Integration full run exposed two optional-IP exception regressions, fixed with a new failing test and 92-test final run; full suite remains non-green for unrelated/environmental reasons. Detailed counts, limitations and log locations: /tmp/guided-fixes-20261125-summary.json.
