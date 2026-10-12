# Cluster resources implementation plan

**Goal:** implement filesystem, cache group and client mount management per registered cluster.
**Architecture:** fixed command/helper layer; bounded authenticated persistent jobs; per-cluster UI forms and results.
**Spec:** docs/superpowers/specs/2026-09-24-cluster-resources-design.md

## Constraints
Preserve all existing changes. Use only local directed tests. No live cluster mutations. UI/backend enforce owner/admin and machine ownership. Never persist plaintext credentials or accept arbitrary command strings from browsers. Retain user data directories when deleting registrations.

## Tasks
- [x] Command contract and strict parameter validation, bounded remote lifecycle helper; tests first.
- [x] Persistent resource/operation models, migration, target authorization, idempotency, secret handling and step execution; tests first.
- [x] Three management panels, forms, confirmation, auth recovery, operation results and log view; tests first.
- [x] Integrate existing cluster transport/operation exclusion, generate OpenAPI, run targeted tests and production frontend build.
- [x] Review paths/permissions/partial failure/secret redaction, document deployment and acceptance, synchronize with hash checks.

## Review focus
Wrong-cluster MDS target, another owner's SSH credentials, replays after lost responses, multi-member partial failure, child process and mount ownership validation, storage secrets appearing in output, lease expiry and sudo challenge resumption.

## Verification

New command/helper tests: 34 passed; API tests: 14 passed; output redaction: 6 passed. Related cluster control/discovery/parser/transport tests passed. Frontend full suite: 75 passed; TypeScript and production build passed. Temporary PostgreSQL migration upgrade/check/downgrade/re-upgrade passed. Independent review findings fixed and covered; no live cluster actions.
