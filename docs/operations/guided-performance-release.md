# Guided performance release and live fio acceptance

## 2026-11-18 release

The user approved upgrading the live platform and DTT, followed by a short
browser-driven fio test on the 126 cluster. Only API/web were recreated; the
database and DingoFS services were not restarted or migrated. No main merge or
remote push was performed.

- Platform API: `0bdbeff`, image
  `dingofs-test-platform-api:guided-performance-0bdbeff`, image ID
  `sha256:ace965b806ff9522bffb1ee1f3afaf27f5dc859c7d544402a7e3a06ae86bc838`.
- Platform web: `3568c1b`, image
  `dingofs-test-platform-web:guided-performance-3568c1b`, image ID
  `sha256:55f3d2d79f1906bdb3307af3e7122de3637c6df06896b7c2d4a2a69db82ae2fb`.
- Release wrapper:
  `/mnt/disk5/daigy/dingofs-platform-releases/20261118-guided-performance/compose.sh`.
  This preserves the previous functional-source, retention, report-cache and
  300-second healthcheck startup settings. API became healthy before switching web.
- Previous API/web images `report-cache-20261117` were retained. The previous
  Compose wrapper is `/tmp/report-cache-compose-20261117.sh`; do not roll back
  during an active task.

### DTT compatibility

Performance source commit: `ece1c41bfd60df8083a70444e5e263434ab41fb7`.
Installed only its tracked performance wrapper, entrypoint, plan/runner/report
modules and MLPerf adapter under
`/home/jenkins/.local/share/dingofs-platform/tools/dtt-performance/ece1c41-20261118`.
The adjacent `current` symlink selects this bundle. The performance resolver now
prefers this executable and falls back to the existing managed/PATH candidates.

The immutable tools image remains
`sha256:3631f4b058a4b58a373f98f8fcec67bb4ab6904532374066010fb2ae96155231`.
The wrapper binds the new performance runtime into that image. The existing
functional DTT bundle at `tools/dtt/current` was deliberately left unchanged:
replacing it with the performance branch would lose functional dispatch and
its installed entrypoint checks. No dirty integration submodule was copied.

## Real Chromium acceptance

Started from the live Start page and completed every performance guide step,
previewed the generated command, and submitted exactly one workload. The existing
browser document required a full reload after the SPA bundle switch.

- Task: `a52e8c8e-d3a3-4bf1-bbb6-f2c82ad18798`.
- Name: `引导网页 fio 短测 20261118`.
- Machine/user: `dingo126` / `172.30.14.126` / `jenkins`.
- Target cluster MDS: `172.30.14.126:6900,172.30.14.126:6901,172.30.14.126:6902`.
- Dedicated filesystem: `platform-fio-guide-20261118-30s`, FSID `10166`.
- Mount: `/mnt/disk5/dingo_autotest/platform-fio-guide-20261118-30s`.
  `findmnt` verified source `DingoFS:platform-fio-guide-20261118-30s`, type
  `fuse.dingofs`; this was not a local-disk substitute.
- Parameters: fio sequential write, 30 seconds, 256 MiB dataset, one file, one
  worker, one round, 1 MiB block, direct I/O, depth 1, five-minute task limit.
- Native fio `3.36` result: error `0`, write runtime `30171` ms, bandwidth
  `1367135133` bytes/s (`1303.80` MiB/s), `1303.80` IOPS. Task wall time: about
  38 seconds. The 256 MiB dataset was rewritten during the time-based test;
  actual total I/O was `41247834112` bytes, not limited to 256 MiB.
- Final state: `success`, progress `100`, phase `全部场景通过，测试数据已清理`.
- The task-specific data subtree was confirmed absent after completion. The
  dedicated filesystem/mount remains available; existing resources were not deleted.
- Browser task detail, scene report and embedded native HTML report loaded and
  agreed with raw fio results. No browser JavaScript errors were observed.

Live task:
`http://172.30.14.126:58080/#/performance/a52e8c8e-d3a3-4bf1-bbb6-f2c82ad18798`.
Raw results/logs remain under
`/home/jenkins/.local/share/dingofs-platform/performance/a52e8c8e-d3a3-4bf1-bbb6-f2c82ad18798`.
Screenshots: `/tmp/fio-guided-live-confirm-20261118.png`,
`/tmp/fio-guided-live-success-20261118.png`,
`/tmp/fio-guided-live-report-expanded-20261118.png`.

## Scope of verification

The isolated-DTT resolver change passed its six targeted tests and all 170
performance backend tests. The complete backend run was not green: 1500 passed,
9 skipped, 31 failed and 2 teardown errors. No performance test failed, but the
full failure set has not been proven identical to the earlier baseline.

This live test validates the short fio guide, execution, reporting and scoped
data cleanup. It is not a sustained/cold-cache performance benchmark and does
not validate real MLPerf, elbencho, mdtest or functional workloads after release.
