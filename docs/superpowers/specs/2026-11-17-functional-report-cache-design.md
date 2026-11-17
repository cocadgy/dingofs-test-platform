# Functional report local cache

## Intent and approved approach

The user chose local platform caching over merely reducing repeated remote reads.
The current report takes about 25 seconds to show its summary and 29 seconds to
finish loading. Each asset revalidates the source archive and rereads a remote
file. The user explicitly does not require report redaction on this internal
platform. Authentication and existing run/machine permissions remain mandatory.
The prior instruction to implement and test without intermediate questions applies.

## Scope

Cache the complete verified module report once on the platform. New completed
reports are prefetched after their observation is committed. Historical reports
populate the cache on first access. All later assets use local files, including
after an API restart or when the original SSH source is temporarily unavailable.
Do not rerun tests, alter test resources, or change legacy v1 reporting behavior.

## Decisions

- Retain child/run identity, verified report location, login, run ownership and
  machine permission checks for every request, including conditional responses.
- Remove source-archive/credential redaction work from v2 report downloads only.
  Return report bytes unchanged; no publicly accessible static report directory.
- Cache keys include run, child, verified report output/path and bound connection.
- Fetch the report tree through a single bounded remote operation/connection;
  reject traversal, symlinks, special files and malformed/oversized archives.
- Stage in a private directory; publish atomically only after complete validation.
  Concurrent requests for one report share a single fill, including across workers.
  A failed fill leaves no ready cache and can be retried.
- Use a dedicated persistent volume. Bound total cache storage and evict old
  reports; cache removal must never delete remote report/test data.
- Serve authenticated private conditional responses (ETag, revalidate on every
  visit) and gzip report text assets. Permission failure never returns a 304.
- Prefetch failures do not change a successful test result; opening the report
  retries and gives a clear error if retrieval still fails.

## Alternatives

1. Reuse connections/validation only: smaller change, but all initial downloads
   remain dependent on SSH and repeated requests still do remote work.
2. Local report snapshot (selected): one remote fetch, then local authenticated
   access; requires a bounded persistent cache and atomic publication.

## Verification

Regression tests cover no redaction, no source archive dependency, one fetch for
all assets, concurrent fill, partial failure/retry, traversal/symlink/size limits,
child isolation, permissions after warming and before 304, and prefetch behavior.
Run the backend suite using a disposable localhost *_test database, never live DB.
Deploy only after checking active tasks, with the old image available for rollback.
Repeat real Chromium first-load and refresh measurements for the same report URL.
