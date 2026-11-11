# Guided functional release and acceptance

Status (2026-11-11): implementation, affected regression tests and the final
independent code review are complete. All three feature branches are pushed.
The authorized fresh production backup and restore verification completed;
production migration and API/web image switching have now completed. Tool
installation and real 126 workload acceptance remain pending. See the live
verification record below for the browser and enabled-readiness result.
Local transport fixtures are not evidence of a real workload.

## Immutable release inventory

| Repository | Reviewed candidate | Branch |
| --- | --- | --- |
| Integration framework I | `17b5e05e8c74caea41df4b630086445f5978763b` | `feat/guided-functional-lifecycle` |
| DTT D | `f644a4023bcd35a4c92ff00b8867e51df5f6bf2b` | `feat/guided-functional-runtime` |
| Platform P code | `01b52495af085f60594f02690017cce9415d28e6` | `feat/guided-functional-existing` |

Verify D's `dingofs-integration-test` gitlink equals the I commit. Record release
API/web image IDs and immutable tags, DTT image ID, installer file hashes, source
manifest digest, source directory and the final P commit in the release record.
Push I, then D with its updated gitlink, then P, only on the approved branches.
Do not switch or rewrite the original dirty working trees.

The three pushes above completed in that order, with remote SHA readback. A
later documentation-only commit records this release status; candidate images
contain exactly the P code commit listed above, not unreviewed application edits.

The read-only baseline audit on 2026-11-10 observed API image
`sha256:f534a8a772340c6a64dd3e4e5a2564d32c8607979bab2e35e3dbe16e482e219b`
and web image
`sha256:b21d576912677842930b5d65531d55b61d76e18e130d922ca87088595d6af598`,
tagged `guided-fixes-20261110`. The live Compose files were under
`/tmp/dingofs-guided-fixes-Q6PkXV/deploy`, including `guided-fixes.override.yaml`.
Reinspect selected image IDs, mounts, Compose labels and health immediately
before release; this historical inventory must not substitute for that check.
Retain the exact previous effective configuration privately, without printing
environment arrays or credentials.

## Verified candidate and remaining release gate

Final affected checks: backend **542 passed** (11 existing Starlette/AnyIO and
Alembic warnings); DTT **40 passed plus 9 subtests**, including five actual
installed-package/container checks; frontend **43 passed**; mocked-API browser
flow **1 passed**; TypeScript/Vite builds passed. Docker execution was isolated
with networking disabled and fake remote transport. Unrelated previously
reproduced baseline suite failures and five existing development/build dependency
advisories remain; this is not a whole-repository-green or security-clean claim.

The single scoped final re-review closed I1–I5 and M1 with no new blocking
regression. Candidate images are:

- API `dingofs-test-platform-api:guided-functional-01b5249`,
  `sha256:a55c56cd09618b560bf3a56d7036f8f0efff883cfb7c8ec2a17fd21a2252926a`.
- Web `dingofs-test-platform-web:guided-functional-01b5249`,
  `sha256:52a1f17c4c8e238dccabcb189bc4aa6cbb11ef877955c68ca1d1bb4002efd2aa`.

The actual API UID 10001 verified current and historical source binds read-only.
The historical full-source key is
`facca2fc534340633e26f789776f0166bef89b88353217983b7b14161aec3ad9`
(1,042 files, eight materialized aliases). An isolated restore of the previously
verified private backup migrated from `2f6d6db8c141` to `7b1c9e4a602d`, retained
18 functional runs, 12 performance runs, 13 machines and seven clusters, and
returned enabled readiness 200. No application lifespan/workers or real remote
targets ran in that rehearsal.

The first fresh-backup attempt was denied before execution. The user then
explicitly authorized a local private production database backup. The new
`private/platform-before-guided-01b5249.dump` is mode 0600 under a 0700 directory,
2,022,849 bytes, SHA256
`0a69c7afdf8fb4c44dffb69c81a0daa25ef0674a992786c9627837a53d403b3b`.
Its isolated, no-network PostgreSQL restore succeeded and retained the expected
legacy revision and counts. The temporary restore container was removed after
identity verification; the private backup is retained.

The controlled production migration exited zero at `7b1c9e4a602d`, retaining
18 functional and 12 performance runs. Only API/web were switched to the image
IDs above; database and external daily containers were not recreated. With
creation disabled, authenticated history verification passed and the tool source
was updated/read back at revision 2: immutable `source-dtt-f644a40`, registered
126 machine, pinned tools image digest, and `allow_cached=false`. This was a
configuration update, not a tool installation or workload submission.

Initial API startup parsed all predefined environments before serving requests
and exceeded the original five-healthcheck startup window. API subsequently
became ready without a code change. The private release override now sets
`services.api.healthcheck.start_period: 300s`; the enabled API was recreated
with this grace period. Keep this setting with the release Compose invocation;
do not bypass readiness or increase its ordinary request timeout. The release
uses explicit `PLATFORM_GUIDED_FUNCTIONAL_ENABLED=true` and the two immutable
source/archive environment paths on every Compose invocation.

External daily tests still occupy 126; real workload acceptance must wait for
that independent conflict to clear. Local transport fixtures are not evidence
of actual remote installation or workload cleanup.

### Live verification (2026-11-11)

The enabled API returned HTTP 200 with
`{"status":"ok","guided_functional":"ready"}`. Real Chromium login at
`http://172.30.14.126:58080` and navigation through Start → Functional Test
passed: the environment-selection page showed seven registered clusters and
104 environment options, with no page/API errors or premature completion page.
The browser allowed only same-origin reads and authentication; zero workload
submissions and zero tool installations occurred. The second startup completed
within the 300-second grace period. This is deployed-entry validation, not a
completed real integration test or remote cleanup acceptance.

## Source, installer and permissions

Set `PLATFORM_INTEGRATION_SOURCE` to a dedicated immutable snapshot of I. Compose
requires this explicit directory, mounts it read-only at `/app/integration-test`,
and refuses to create a missing host directory. The API expects
`PLATFORM_FUNCTIONAL_SOURCE_ROOT=/app/integration-test/testcases`.

Prepare a private release copy with narrowly granted read/traverse access for
API UID 10001 (the image's `platform` account). A dedicated release group or ACL
is suitable; directories may be 0750 and sensitive configuration 0640 for that
group. Verify each parent directory is traversable by UID 10001. Never make the
secret `conf` tree world-readable, and never chmod/chown original repositories.
Keep old immutable sources for historical report redaction and rollback.

### Historical report source archive

Set `PLATFORM_FUNCTIONAL_SOURCE_ARCHIVES` to a dedicated private host directory,
separate from release backups, environment files and tool-installation data.
Compose requires this directory, refuses automatic creation and mounts it
read-only at `/app/functional-source-archives`. The API setting is
`PLATFORM_FUNCTIONAL_SOURCE_ARCHIVE_ROOT=/app/functional-source-archives`.
This archive is independent of the current `/app/integration-test` bind.
Once configured, it is authoritative: a missing or invalid historical entry
returns `report_redaction_unavailable`, without trying current credentials.
Development configurations that omit the archive retain exact-current-source
verification only; they do not support report access across source upgrades.

Publish one entry for every full `functional_runtime.source_manifest` admitted
by the server. The layout is `<archive>/<manifest-key>/source/<relative-file>`.
Use the full installer manifest, not the selected-child descriptor's subset.
For a source staged before installation, obtain that same full manifest from
the existing DTT `functional_runtime.collect_source` collector with its reviewed
alias map, or platform `functional_source_files` (second return value). Record
and compare it with the actual install capability before admitting work.

The platform provides the canonical key/verification helper; with the candidate
API interpreter/package and a private JSON file containing only that manifest:

```sh
python -B -m dingofs_platform.functional.source_archive key --manifest "$SOURCE_MANIFEST_FILE"
python -B -m dingofs_platform.functional.source_archive verify \
  --manifest "$SOURCE_MANIFEST_FILE" --archive "$PLATFORM_FUNCTIONAL_SOURCE_ARCHIVES"
```

The key is SHA256 of the manifest's sorted compact JSON (default ASCII escaping).
Prepare a new staging directory outside the mounted archive, copy exactly the
manifest entries from the reviewed immutable source, and materialize approved
in-tree file aliases as regular bytes. Do not copy `.git`, bytecode, extra files,
or undeclared directories. Verify every file hash. Set the archive root to 0700,
the entry/source/subdirectories to 0500, and files to 0400, owned by API UID
10001 (or root only when the API can actually read them). This archive intentionally
does not use group-readable source-copy permissions. Publish by an atomic rename
under the manifest key without overwriting any existing entry. Run `verify` again
as UID10001 through the actual read-only API bind with networking disabled.
The helper prints only the key; never print environment contents or credentials.

Every report read rejects symlinks, untrusted owners, group/other permissions,
writable entry contents, added/missing files and changed hashes, before importing
the archived parser and again after collecting redaction credentials. Bounds are
16,384 files, 32 MiB per file, 256 MiB total and 4 MiB manifest JSON. Sources are
reviewed administrator-provided code; integrity checks are not an untrusted-code
sandbox. Retain entries for as long as their reports remain accessible, including
rollback versions. Never prune based only on the current source version. Archive
publication/retention is an operator action, not an HTTP path or upload option.

The tool-source configuration is separate from the API bind. In Configuration
Management → Tool Packages, use the reviewed immutable D directory containing
the exact I gitlink and the pinned DTT image. The legacy suggested directory
`/mnt/disk5/daigy/dingofs-testsuite-tool` is an original working tree and is not a
release source. Read back the saved source machine, directory, image and revision
before any explicitly confirmed installation. Installation destinations must
be owned by the execution user, with private directories 0700 and secret
configuration 0600. Merely mounting I into the API does not update this source.

Build the candidate image, then run the read-only inspector as the actual API
user, against the immutable bind, with Docker networking disabled. For example,
using the candidate API image ID and the approved source directory:

```sh
docker run --rm --network none --user 10001:10001 \
  --mount type=bind,source="$PLATFORM_INTEGRATION_SOURCE",target=/app/integration-test,readonly \
  "$RELEASE_API_IMAGE" python -I -B -c \
  'from pathlib import Path; from dingofs_platform.functional.source_bridge import inspect_source; value=inspect_source(Path("/app/integration-test"), "__platform_readiness__", {}); print("source ABI readable")'
```

Provide the intended release group/ACL in this check if supplementary group
access is used in deployment. Do not emit the parsed environment or credentials.
PyYAML 6.0.3 is pinned in the API dependencies for the pure inspector; the API
does not execute Allure or import the workload executor. DTT owns workload and
report generation dependencies. Verify the real execution interpreter supports
the framework's union type annotations; a binary named `python3` may be Python
3.9 and unsuitable. A source-only compatibility descriptor does not prove remote
tools, ownership, filesystem schemas, mount identity, or recovery capability.

## Creation gate and task continuity

`PLATFORM_GUIDED_FUNCTIONAL_ENABLED` is the supported environment key and defaults
to false. The historical spelling `PLATFORM_FUNCTIONAL_GUIDED_ENABLED` is not the
deployment key. Enabled readiness requires the exact Alembic head
`7b1c9e4a602d`, all mapped V2 persistence columns, and successful execution of the
isolated pure source inspector. Source import checks cache positive results for
at most 30 seconds; preflight and submission continue their own uncached exact
source/permission/runtime checks. Readiness does not advertise all 12 modules as
runnable: each selected module/case/environment must pass its actual capability
and remote preflight checks.

The default-off `/health/ready` preserves the ordinary database health contract.
When enabled, migration or source failure returns 503 and blocks new guided
metadata, compatibility, preflight, V2 submission and V2 rerun. Authentication and CSRF
checks retain precedence. History, reports, stop and residual verification remain
available subject to their normal authorization and evidence checks.

Compose sets `PLATFORM_FUNCTIONAL_WORKER_ENABLED=true` independently of creation.
The functional worker also preserves the previous performance-worker startup
behavior. Turning creation off must not stop monitoring accepted queued, active
or unknown V2 runs. Keep a compatible worker and frozen runtime/source available
until every accepted task has authoritative terminal evidence. An unknown child
is polled after restart; it is never launched again to resolve uncertainty.

After the 600-second cancellation grace, an attempted child in `needs_attention`
continues observation across worker restarts. No later module starts; leases
remain until the existing end/recovery/cleanup checks prove safe completion.
The parent end timestamp stays unset until final evidence arrives. Public V2
parent/child responses and child results expose `termination_cause`: `timeout`,
`manual`, or null. The terminal state remains `cancelled` after a safe timeout,
with its cause preserved; a subsequent manual stop cannot overwrite timeout.
Existing cancelled-run rerun rules remain unchanged.

New requests may queue behind a database-verified, positively running V2
functional owner. Unknown, cancelling, retained or unrelated operation owners
remain admission failures. `resource_wait` and `prerequisites_deferred` explain
that admission has not reserved resources or proven occupied hosts ready. The
worker must acquire the full exclusive lease union and freshly validate source,
permissions, runtime and all deferred host prerequisites before launching.

New complete-source DTT packages also preserve custom/legacy exact-plan calls
with `--case-plan` and `--int-env-file`. They verify the installed package before
host launch and container imports, mount the whole framework read-only, and add
the custom environment through a private temporary configuration copy. Legacy
calls retain their own lifecycle semantics; they do not acquire guided context
authorization. Private HOME, execution UID and bytecode refusal also apply.

## Migration rehearsal and deployment sequence

Local rehearsal uses only the exclusive loopback `guided_functional_e2e_test`
database. `test_actual_upgrade_downgrade_upgrade_changes_enabled_readiness`
creates a fresh named schema, runs real Alembic `upgrade head`, checks enabled
readiness, downgrades an empty V2 schema to `2f6d6db8c141`, verifies 503, then
upgrades again and verifies 200. It removes only its own temporary schema.
The submission suite additionally checks legacy-row preservation and refuses
downgrade when V2 task rows exist. Test fixture migration-marker stubs are not
used in the readiness/rehearsal checks.

Before the authorized production switch:

1. Requery migration revision and bounded task states, selecting only IDs and
   timestamps for functional, performance, tool, resource and cluster operations.
   Review queued/pending/running/cancelling/unknown/interrupted tasks and held
   leases. Prove compatibility or postpone switching; DB status alone cannot
   prove remote absence. The old audit found no active/unknown tasks, but its
   result is time-sensitive.
2. Save an access-controlled PostgreSQL custom-format backup outside Git,
   alongside the private old Compose configuration and immutable image/source
   inventory. Verify the backup can be restored into a separate empty database.
   Do not print database credentials or backup contents.
3. Set the reviewed immutable source explicitly and leave creation disabled.
   Build and tag the reviewed candidate images, verify UID 10001 source access,
   and verify the saved DTT source points to the reviewed D/I pair.
4. Run the commands below from the approved P release checkout using the private
   environment file. Record resulting image IDs and migration revision.

```sh
docker compose --env-file "$RELEASE_ENV_FILE" -f deploy/compose.yaml build api web
docker compose --env-file "$RELEASE_ENV_FILE" -f deploy/compose.yaml run --rm migrate
docker compose --env-file "$RELEASE_ENV_FILE" -f deploy/compose.yaml up -d api web
```

5. Check ordinary readiness, existing task/history/report access and worker
   continuity. Enable `PLATFORM_GUIDED_FUNCTIONAL_ENABLED=true` in the private
   release configuration and reload the API. Require enabled readiness 200 with
   `guided_functional=ready`, then check permissions and the guided entry. A
   failed capability check closes new creation; do not bypass it in the UI.

## Rollback and retained resources

Close new creation first by setting the flag false. Keep the compatible worker
running and preserve accepted/unknown tasks, leases and frozen runtime/source.
Restore the recorded compatible API/web image and configuration only after
checking support for the current schema and accepted V2 tasks. The pre-feature
image cannot safely monitor V2 rows; if V2 work exists, use a known compatible
release with creation disabled. Never delete rows or clear leases to obtain
green health. Never use `docker compose down -v`.

The migration deliberately refuses downgrade when any V2 run exists. The empty
test-schema downgrade rehearsal does not authorize a production downgrade after
new writes. Restore a backup only to a separate empty database after an explicit
data-loss/continuity decision. Preserve old sources for report redaction.

The result-page “重新检查残留资源” action calls the authenticated read-only
`POST /api/v1/functional/runs/{id}/resources/verify` with no client evidence.
Remaining resources keep owner leases; unknown end/recovery evidence blocks
release. This action does not remove resources. Use separately authorized
resource-management cleanup for exact owned resources, then recheck; do not
force-kill processes, mutate borrowed resources or broad-clean by name prefix.

## Bounded real acceptance — pending

After explicit release authorization and conflict checks, use the browser to
select `env_126_trash`, module `trash`, and only
`trash_test_cases/smoke/TC-SMOKE-001.yaml`. Reinspect the final source hashes and
actual read-only prerequisites before confirming the run. The audited case
creates one child-owned filesystem/mount and one 1 MiB file, checks trash
behavior, and then performs owned cleanup. Exclude fault injection, service
stops, cache kills, large-scale tasks and other modules.

Record parent/child IDs, frozen source/runtime digests, target user, actual
created/mounted identities, case result, cleanup/recovery evidence, retained
resources and the child-scoped Allure URL. Confirm independent report access
and that credentials are redacted. Until this is performed, acceptance remains:
“本地闭环通过，真实环境待验收”; no full-environment validation claim is warranted.
