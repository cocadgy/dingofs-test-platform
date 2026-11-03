# Cache directory sudo fallback implementation plan

> Execute sequentially using superpowers:executing-plans after plan approval.

**Goal:** Prepare missing cache base directories through sudo only when normal creation lacks permission.
**Architecture:** Add a narrow directory preparation helper called by cache.plan. Keep cache processes running as the selected execution user. Existing directories and their contents must never be chowned or chmodded.
**Tech Stack:** Python remote helper, subprocess, POSIX directory file descriptors, pytest.
**Spec:** User-approved conversation: normal creation first, sudo fallback, new base owned by execution user with mode 0750; existing paths unchanged; explicit sudo failure.

## Global constraints
- Apply only to cache base directory preparation, not arbitrary resource actions or cache binary execution.
- No chmod 777, recursive chown, recursive chmod or changes to existing ancestors.
- Reject symlink components, traversal, root paths and non-directories; quote arguments, never concatenate untrusted shell commands.
- Only chmod/chown a directory this invocation demonstrably created, using opened descriptors; a concurrent creator's directory is treated as existing.
- Missing intermediate directories may be created with traversal permission; only the final new cache base belongs to the execution user.
- Check read/write/execute access again as the execution user before returning success.
- Use bounded noninteractive sudo; unavailable or password-required sudo produces an actionable error, never hangs or embeds passwords in arguments.
- Preserve unrelated working changes. Capacity dropdown work has its own existing plan and remains pending.

## Review focus
Existing directories with other owners; symlink replacement races; partially missing parents; denied sudo; execution user different from SSH login.

## Task: Safe base-directory preparation
Files: new resources/cache_directory.py, resources/remote_helper.py, resources/commands.py (helper packaging), new tests/test_cache_directory.py and cache plan integration tests.
Interface: prepare_cache_directory(path: str) -> None; permission failure invokes a fixed root helper with the invoking execution UID/GID, then rechecks access under the execution user.
- [ ] Write tests proving normal creation needs no sudo, absent directory permission failures invoke sudo, and newly created base has selected ownership and 0750 permissions.
- [ ] Add tests proving existing inaccessible directories, existing ancestors and contents remain unchanged; symlinks/concurrent creation are rejected without mutation; sudo denial is visible and bounded.
- [ ] Run tests to observe expected failures before implementation.
- [ ] Implement descriptor-based directory creation and scoped sudo helper; integrate into cache.plan without elevating the whole cache preparation/start workflow.
- [ ] Run focused helper and cache-plan tests, review privilege boundaries and error propagation.
- [ ] Implement previously planned capacity selector separately; build scoped API/web images, commit only relevant files, deploy and verify health/assets.

**Recommended execution:** Current-session sequential implementation, with a focused security review before deploying the sudo path.
