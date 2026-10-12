# Cluster logs and terminal implementation plan

Goal: service log inspection and administrator web SSH terminal, preserving existing ownership and credentials.
Architecture: aliases resolve service hosts; bounded remote worker enforces filesystem confinement; DB-backed remote sessions authorize requests and stream events over WebSocket; frontend offers service logs and admin-only terminal.
Spec: ../specs/2026-09-24-cluster-logs-terminal-design.md

User authorized autonomous implementation with reasonable defaults. Do not ask further design/implementation approvals. Work in an isolated complete snapshot, retain SHA256 baseline, synchronize changed files only. Do not execute commands on real cluster nodes, commit, push or restart production.

- [x] 1. Add machine host aliases, normalization, unique-resolution semantics and migration. Test collisions, IP/hostname normalization and creator authorization.
- [x] 2. Add supervised SSH worker and confined remote log helper. Test safe file opens, internal links, escape/race rejection, special files, bounded tail/download, rotation and incremental decoding. Verify authentication before operation, terminal sizing, bounded queues and process cleanup with loopback/fakes.
- [x] 3. Implement persistent remote-session authorization and APIs. Test owner+machine permissions, admin-only terminal, confirmation, scoped file IDs, session revalidation/revocation, retry bounds, quotas, origin/WS checks, downloads and metadata-only audit.
- [x] 4. Add log viewer and terminal UI, machine alias form, scoped navigation and Nginx WebSocket configuration. Test confirmations, literal text filtering, bounded buffer and readonly restrictions. Bundle terminal dependencies locally.
- [x] 5. Integrate schema, migration and deploy configuration; run backend/frontend tests, production build and isolated browser validation. Update acceptance docs, synchronize source with baseline checks, remove owned temporary services. Report result without deploying.

Review focus: logs on someone else's machine; changed log directory during stream; symlink races; missing/changed host key; expired user session during output; non-consuming clients; process or API restart; cancellation does not terminate arbitrary remote background jobs; no terminal payload in database/audit/logs.

Verification: backend full regression 213 passed; final network-disconnect regression added and remote/API/loopback checks rerun. Frontend 55 passed, TypeScript/production build passed, two browser flows passed with unchanged deployment CSP. Alembic upgrade/downgrade/re-upgrade and metadata check passed; Nginx configuration and Compose configuration validated. SSH tests used only local ephemeral servers. Source synchronization verifies the original SHA256 baseline before copying changed files.
