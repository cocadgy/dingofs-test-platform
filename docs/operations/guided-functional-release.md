# Guided functional release and acceptance

Status: local integration and release preparation only. Production deployment,
tool installation and the 126 browser smoke remain pending the controller's
release gate. Local transport fixtures are not evidence of a real workload.

## Immutable release inventory

| Repository | Reviewed candidate | Branch |
| --- | --- | --- |
| Integration framework I | `17b5e05e8c74caea41df4b630086445f5978763b` | `feat/guided-functional-lifecycle` |
| DTT D | `7e74101a0e77c2434aca7003f4410bdfa6e74aa8` | `feat/guided-functional-runtime` |
| Platform P | Record final reviewed Task 11 + Task 14 commit at release | `feat/guided-functional-existing` |

Verify D's `dingofs-integration-test` gitlink equals the I commit. Record release
API/web image IDs and immutable tags, DTT image ID, installer file hashes, source
manifest digest, source directory and the final P commit in the release record.
Push I, then D with its updated gitlink, then P, only on the approved branches.
Do not switch or rewrite the original dirty working trees.

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
