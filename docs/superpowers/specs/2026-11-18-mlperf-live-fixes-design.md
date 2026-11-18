# MLPerf live regression fixes

The user approved fixing the three issues diagnosed in the 126 browser tests.
Keep the existing MLPerf v2.0 image, training modes and task lifecycle. No main
merge, remote push, database migration or changes to historical task results.

1. UNet3D training can finish before its first checkpoint (epoch 5). Its native
   summary then contains NaN in four unused checkpoint aggregate fields. Accept
   unavailable optional checkpoint aggregates as missing, not zero; retain strict
   validation of every consumed training metric, plan, epochs and attachments.
   Do not globally loosen metadata or duration validation. Preserve native bytes
   as evidence; generated platform/adapter summaries must remain valid JSON.
2. CosmoFlow's pinned TensorFlow reader has four threads. Native formula is
   floor(ceil(samples/ranks)/4), which must not be zero. Require at least four
   files per simulated accelerator in addition to three complete batches. Keep
   normalization and explicit-count rejection consistent in frontend, backend and
   DTT. For 1 MiB/one accelerator: four files, 11,313,944 nominal bytes. For two
   accelerators: eight files, 22,627,888 bytes. ResNet50 and UNet3D stay unchanged.
3. Permit same-origin MLPerf report embedding in the existing scoped Nginx
   performance-report location; keep general API/page framing restrictions.
   Do not disable protection site-wide. Preserve fio/elbencho behavior.

Approach: repair adapter compatibility and normalize small datasets, rather than
forcing users to choose five epochs or a larger dataset. Raising epochs is a
workaround and violates valid short-test intent. Proxy-only change handles report
embedding; no report API or database redesign is needed.

Acceptance: add failing tests before changes; include actual native-shaped
checkpoint fields, invalid required metrics, 3/4-file and multi-rank boundaries,
and effective proxy response headers. Re-run real 126 browser guide with one
epoch and smallest requested dataset for all three models. Check native results,
embedded HTML, task data cleanup and preservation of earlier failed evidence.
