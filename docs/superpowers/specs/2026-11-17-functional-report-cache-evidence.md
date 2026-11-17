# Functional report cache — deployment evidence

## Result

Deployed to 172.30.14.126:58080 on 2026-11-17. The selected module report is
served unchanged from a private, persistent platform cache, with authentication
and resource authorization checked for every request. No report redaction is
performed on this v2 route, as requested. New reports are prefetched in separate
bounded workers; historical reports fill the cache on first access.

Report: run `6e23f0b5-fc97-44d9-83c7-ee0299a277f4`, module
`ce14296e-b026-469c-97b2-312148366a0d` (`basic_file_operation`).

## Real-browser measurements

Chromium, same report and 1600 × 1000 viewport. Cold means an empty browser cache;
the post-change cold visit also populated the new server cache. Warm means reload
in the same browser context. These are individual observations, not percentiles.

| Metric | Before | After |
|---|---:|---:|
| Cold summary visible | 25.351 s | 3.179 s |
| Warm summary visible | 25.390 s | 0.408 s |
| Cold network idle | 29.595 s | 3.689 s |
| Warm network idle | 29.401 s | 0.905 s |
| Cold encoded response bodies, 14 report requests | 2,411,614 bytes | 992,214 bytes |
| Warm downloaded response bodies | 2,411,614 bytes | 0 bytes |

Cold transferred bodies decreased 58.9%; decoded sizes match the original report.
Network-idle timings include the browser's idle waiting interval. Warm requests
still send authorization/revalidation requests; some browser APIs normalize a
revalidated response to status 200 rather than exposing the wire 304.

Acceptance checks:

- Overview renders 32 passed / 32 total / 100%, without JavaScript errors.
- Large HTML, CSS and JavaScript assets use gzip; ETags are present.
- Authenticated summary GET: 200. Matching conditional GET: 304.
- Anonymous request with the same ETag: 401, not 304 or report contents.
- A new browser context opened a test-case detail in 0.988 s; all 8 requested
  report assets returned 200, without JavaScript errors.
- The selected test's Command, Actual Output and Step Result attachments returned
  200 with nonempty original contents (391, 212 and 49 bytes respectively).
- External Google analytics is blocked by the existing CSP; it is not a failed
  report asset and does not prevent report use.

Raw local evidence: `/tmp/allure-perf-20261117.json`,
`/tmp/allure-cache-perf-20261117.json`, `/tmp/allure-cache-details-20261117.json`;
screenshots use the matching cold/warm/details filenames in `/tmp`.

## Automated verification and independent review

- Final production Python 3.12 API image: **59 passed**, 2 existing deprecation
  warnings, 86.07 seconds, covering cache, API authorization/ETag, prefetch,
  report/source compatibility and end-to-end behavior.
- Initial full backend suite: **1,406 passed, 31 failed, 9 skipped, 2 errors**,
  884.07 seconds. One stale report E2E fixture was updated for the new whole-tree,
  unredacted transport; the entire E2E test file subsequently passed and is
  included in the final 59-test run.
- All other **30 failing node IDs and both teardown errors** reproduced on
  unchanged deployed baseline `98a0ee3`, with identical failure/error node sets.
  These concern existing asset/cluster permissions, scheduler timing, host trust,
  credentials, remote sessions/security and resource commands/batches. They are
  not claimed fixed; the complete suite is not claimed green.
- Backend review, focused prefetch fix review and whole-branch integration review
  found no remaining critical or important issues.
- Effective Compose configuration and actual image Nginx syntax validated.
  Cache volume is writable as UID 10001 with mode 0700.

Logs: `/tmp/report-cache-final-image-tests-20261117.log`,
`/tmp/report-cache-full-suite-20261117.log`,
`/tmp/report-cache-baseline-failures-20261117.log` and corresponding baseline XML.

## Operational limits

Default aggregate cache budget is 2 GiB with oldest-idle snapshot eviction.
Report ingestion limits are 8 MiB per file, 64 MiB total report payload, 4096
entries and depth 32. A file/report exceeding these limits rejects the **entire**
snapshot and returns `503 report_cache_unavailable`; partial reports are never
published. This is a known compatibility limitation versus the former per-file
route, which could still display an overview with an oversized attachment.
The measured report is below the limits; this check does not establish
compatibility with all larger historical reports. Cache eviction affects only
local copies, never remote test results.

## Deployment and rollback

Only API and web were recreated, after a read-only check found zero active
functional/performance tasks, tool jobs, resource/cluster operations, remote
sessions and unreleased operation leases. No database restart, migration, test
rerun or remote test-resource deletion occurred. API became healthy, followed by
web recreation to refresh its API upstream address. Both services are running.

Source commits: `badf20b`, `8b53270`, `6954898`.

| Service | Deployed image | Image digest |
|---|---|---|
| API | `dingofs-test-platform-api:report-cache-20261117` | `sha256:b0f61aabdea85d2ef4f0b614190ed5b083e51b3ece4f37a682067fd72a34ec2d` |
| Web | `dingofs-test-platform-web:report-cache-20261117` | `sha256:632f3cf211ddd69e465f3fe123759afcbf6d1fba28871a7e776563e58c571f44` |

Release directory:
`/mnt/disk5/daigy/dingofs-platform-releases/20261111-guided-functional`.
The new `report-cache-20261117.override.yaml` is layered after the existing three
Compose files. Deployment wrapper: `/tmp/report-cache-compose-20261117.sh`.
The volume `dingofs-test-platform_report-cache` persists independently of API
container replacement.

Rollback uses the original three Compose files, omitting this new override, and
recreates only API and then web with `--no-deps --no-build`. The original
`retention-release-20261113` images are retained. Keep the report-cache volume;
no database rollback or deletion is required.
