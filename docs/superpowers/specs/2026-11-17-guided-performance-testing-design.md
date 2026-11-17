# Guided performance testing

## Scope

Add a four-step Chinese-language guide under Start → Performance testing, using the existing DTT remote job lifecycle and performance report pages. User delegated design choices and requested no intermediate questions. No cluster is available: all verification is local or mocked; do not start cluster workloads, deploy, or restart services.

## Flow

1. Test location: choose a manageable machine (name, IP, SSH user), then a saved mounted filesystem or an absolute directory. Empty/maintenance machines and unavailable mounts are explained. Only a task-specific subdirectory is used.
2. Tools: multi-select fio and elbencho, with brief descriptions. mdtest stays available in the existing advanced performance page because metadata count is not a byte/time workload.
3. Parameters: task name; measurement duration per tool per round (seconds/minutes/hours, default 60 seconds); total dataset size per tool (MiB/GiB/TiB, default 1 GiB); read/write mode (default sequential write). Collapsed advanced options: concurrency (default 4), block size (default 1 MiB), rounds (default 1), direct I/O, I/O depth, mixed-read percentage, cleanup on success, total timeout. Dataset bytes are independent of duration and rounds; each selected tool has its own retained dataset. Read/mixed preparation and sync are outside measurement time. Show estimated measured time and combined retained data size. Timeout must exceed measurement time; preparation overhead remains variable.
4. Confirm: show machine/IP/user, target, tools, duration, data size, generated DTT command and normalized parameters from existing preview API. Preview is configuration validation, not a remote tool health check. Start once, then navigate to existing task detail with logs/results/reports. Submission failures stay visible; never auto retry ambiguous submission. Editing invalidates preview. Fresh entry never opens an old completed task.

## Contracts

- Add optional scalar `runtime_seconds` to performance specs/matrices, integer 1..604800; absent preserves finite-volume behavior. Reject runtime on mdtest rather than silently ignoring it. Parameter matrices can expand runtime candidates consistently with other axes.
- DTT adds `--runtime-seconds N` through wrapper, container entrypoint and Python plan. Existing vdbench `--duration` is untouched. fio measured phases use time_based/runtime; elbencho uses infloop/timelimit. Preparation remains finite.
- Timed reports distinguish dataset bytes and actual I/O bytes and preserve measured runtime. Do not require timed I/O bytes to equal dataset bytes. Zero/incomplete I/O and short measurements must not be reported as successful.
- Old DTT must fail clearly, never silently ignore the runtime. Add an offline dry-run contract check before starting a timed workload, compare requested runtime in the emitted plan. Existing finite jobs remain compatible.
- Preserve existing authorization, leases, cancellation, mount identity, data cleanup boundaries, and unknown-state protection. No new blanket permissions or cluster mutations.

## Verification

TDD for duration contract, command forwarding, timed result handling, API persistence/rerun, guide transitions/validation, preview invalidation and one-shot submission. Run existing suites and report pre-existing failures explicitly. Browser flow uses mocked API only. Optional native smoke runs use new temporary local directories and small datasets, never a cluster. No deployment is part of this change.
