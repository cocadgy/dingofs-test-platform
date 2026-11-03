# Cache image TAG selection implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the guided commit selector with descending-update-time Docker Hub TAG selection and centrally cached binary distribution.
**Architecture:** Query only metadata before confirmation. Pin the linux/amd64 manifest digest in each member; after confirmation download verified layers to the platform cache, extract only the cache executable, upload through SSH, and validate it under the execution user before any cache starts.
**Tech Stack:** FastAPI, urllib, tarfile, Paramiko, React.
**Spec:** User-approved conversation: TAG dropdown sorted newest first; choose machines before download; platform caches and distributes; defaults and custom directories unchanged.

## Global constraints
- Fixed repository dingodatabase/dingofs; no caller-provided URLs.
- No fallback to another TAG/default. No overwrite of default installed components.
- Cache by immutable digest; persistent platform volume; target user's ~/.local/share/dingofs-platform/cache-binaries/<digest>/dingo-cache.
- Preserve unrelated worktree changes. Commit and deploy only scoped changes.

## Review focus
- Mutable latest: preserve selected digest across all nodes.
- Missing/unsupported artifact or libraries: explain failure before startup.
- Cancellation, timeout, interrupted copy: no partial binary published or service started.
- Archives: verify layer digest, never extract arbitrary archive paths or symlinks.
- Pagination/search: newest first, stale responses cannot change the selected image.

### Task 1: Registry and cache
Files: resources/cache_images.py, tests/test_cache_images.py.
Interface: list_tags(page, search) -> items/count/next_page; ensure_cached(digest, root, cancelled, deadline) -> path/sha256/size/digest.
- [x] Write tests for sorted query, digest preservation, safe extraction and corrupt/missing/cancelled artifacts; observe RED.
- [x] Implement bounded metadata, checksum-verified layer download and locked atomic persistent cache.
- [x] Run focused tests and verify GREEN.

### Task 2: Member preparation
Files: resources/cache_transfer.py, cache_binary.py, execution.py, schemas.py, commands.py, routes.py, port_planning.py; deploy/api.Dockerfile and compose.yaml.
- [x] Test tag validation and remote checksum failure before activation.
- [x] Add tag/digest member fields, SSH temporary upload and target-user atomic install. Cleanup only owned temporary paths.
- [x] Integrate central cache outside DB locks, cancellation and clear failure results; allow cold download time and post-success plan lifetime.
- [x] Run focused backend and API integration tests.

### Task 3: Guided selector and release
Files: guidedCacheModel.ts, CacheTagSelector.tsx, GuidedCacheFlow.tsx and tests.
- [x] Test metadata-only selection, ordering, search and payload digest pinning.
- [x] Replace commit input, migrate old saved drafts to unselected TAG, preserve default/path.
- [x] Build isolated staged snapshot, review diff and run tests.
- [ ] Commit, deploy API/web and verify health/assets.

## Verification results
- Focused backend: 75 passed; resource API integration: 37 passed; guided frontend: 40 passed.
- Independent review: fixed and reproduced handshake timeout, cleanup disconnect and bounded/cancellable archive parsing; 12 regression tests passed.
- Full backend: 732 passed, 20 failed, 2 errors. All 20 failures and 2 errors reproduced on baseline 51e0350 in the same five test files (11 passed).
- Full frontend: 447 passed, 7 failed. All seven failures reproduced on baseline 51e0350 (89 passed in the affected files).
- API and web images built successfully from the staged-only snapshot; unrelated workspace changes excluded.
- Real Docker Hub metadata and digest-verified manifest lookup succeeded. Full production-size download/distribution remains to be exercised by the user; no cache service was started for testing.
