# 引导式性能测试：交付与验证

## 使用方式

部署新版本后，从「开始 → 性能测试」进入。四步为测试位置、选择工具、设置参数、确认启动。选择机器时显示名称、IP 和 SSH 用户；可使用平台已保存的挂载点，也可指定目录。

- 首版引导支持 fio 和 elbencho 多选；mdtest 和参数矩阵继续使用原高级性能页。
- 测量时长支持秒、分钟、小时，表示每种工具每轮的测量时长，不包含数据准备与同步。
- 每工具数据量支持 MiB、GiB、TiB；并发、块大小（含 KiB）、轮数、读写模式、I/O 深度等可配置。
- 确认页展示实际 DTT 命令、规范化参数、预计测量时间和数据占用。预览仅验证配置，不声称已远程检查机器。
- 启动后复用性能任务详情、日志、停止、重跑和报告；报告区分请求时长、原生测量时长、数据集大小和实际 I/O。
- 原有按固定数据量执行的任务不受影响。新定时任务需要同时更新 DTT 包装脚本与镜像内运行代码，支持 `--runtime-seconds`。旧 DTT 会明确提示升级，不会忽略时长继续执行。

## 本次边界

没有可用测试集群，因此没有部署、重启平台或连接集群运行性能测试。代码保留在本地功能分支，尚未推送或合并到 main。当前线上页面不会因这些本地提交自动变化。

平台分支：`feat/guided-performance-testing`。DTT 分支：`feat/guided-performance-runtime`。真实集群的 SSH、挂载、工具镜像部署及长时压测仍需人工验收。

## 验证结果

- 后端性能专项：最终 128 项通过，包括参数矩阵、旧版 DTT、报告真实性、重跑、超时、取消、场景失败隔离。新增真实子进程回归覆盖预检超时（主进程存活或先退出）、预检取消和无法确认回收时保持 unknown；已有接口测试确认 unknown 不释放机器租约。
- 前端专项：13 项通过；TypeScript 和生产构建通过。模拟 Chromium 完整走通两工具选择、单位转换、预览、单次提交、跳转任务详情。
- DTT 核心专项最终 83 项、158 个子用例通过；Bash 语法检查通过。只使用新建临时目录和小数据集，不使用集群。
- 单并发本机端到端：平台监督执行器 → DTT 规划/执行 → fio、elbencho 原生读测，每工具 1 MiB、2 秒，通过数据准备、真实计时、报告采集和本任务目录清理。
- 四并发本机端到端最终通过：每工具共 1 MiB、4 个文件、4 KiB 块、2 秒读测；最终进程回收修复后复跑 fio 原生最短进程测量 2.000 秒，elbencho 2.002 秒。报告与本任务数据清理成功。过程中发现并修复了有限数据准备阶段合法的 0 毫秒时间戳被误判的问题；定时测量阶段仍不能以 0 毫秒通过。
- 完整分支审查发现的唯一阻塞项（预检未确认子进程回收）已在 `b8f6553` 修复，一次定向复审通过，无新问题。之后根代理再次完成上述 128 项专项和四并发原生联调；真实 Docker/Podman 停止、SSH 与集群挂载仍未实测。
- 后端完整套件：1443 通过、30 失败、9 跳过、2 错误。下列失败没有被隐去；性能专项全部通过。除调度器用例外，失败名与之前完整测试日志一致；调度器用例在改动前 `6052be9` 源码隔离复跑也失败（预期 success，实际 cancelled），确认不是本次性能修改引入。
- 前端完整套件最终复跑：569 通过、7 个既有失败，列于下文；最终 TypeScript/生产构建通过。
- DTT 完整套件：一个既有导入错误阻止收集；排除该文件后 235 通过、2 跳过、2 个本地 HTTP 服务测试失败。未为本功能顺带修改这些无关模块。

## 完整套件非通过项

后端（30 个失败）：

- `test_asset_permissions.py`: `test_members_create_and_only_manage_own_machine`, `test_config_read_shared_but_writes_and_topology_refresh_owned`, `test_owner_can_collect_hardware`。
- `test_cluster_operations.py`: `test_foreign_actor_stale_and_expired_challenge`, `test_concurrency_limit_and_cancel_rejects_late_result`, `test_revoked_actor_during_execution_discards_result`, `test_unreadable_saved_credential_is_reported_as_failed_operation`。
- `test_functional_scheduler.py`: `test_scheduler_persists_all_12000_events_before_terminal_evaluation`（基线也复现）。
- `test_host_trust.py`: `test_missing_known_hosts_allows_safe_fingerprint_discovery`, `test_database_pin_has_priority_and_changed_key_contains_both_fingerprints`, `test_trust_lifecycle_and_replay_rejected`, `test_stale_or_forged_challenge_is_rejected[expired/edited/archived/forged]`（4 个实例）, `test_permission_csrf_and_no_arbitrary_key_acceptance`, `test_address_change_does_not_reuse_trust`, `test_real_ssh_first_contact_and_key_change_never_send_password`。
- `test_machine_credentials.py`: `test_password_crud_never_discloses_secret`。
- `test_remote_e2e.py`: `test_http_list_read_download_through_real_ssh_worker`, `test_http_read_revalidates_symlink_after_listing`（两项同时有 teardown error）。
- `test_remote_security.py`: `test_network_websocket_disconnect_reaps_without_asgi_error`。
- `test_resource_batch.py`: `test_batch_worker_preserves_targets_and_handles_failure` 的 `None-3-succeeded`, `completed-3-failed`, `timeout-2-failed` × `fs.delete_batch-fs_name-fs.delete`, `cache.delete_batch-member_id-cache.delete`（6 个实例）。
- `test_resource_commands.py`: `test_catalog_contains_requested_operations_and_secret_fields`, `test_mds_client_resolves_installed_binary_and_single_reachable_endpoint`。

前端（7 个失败）：

- `CacheGroupInventory > completed deletion removes the entire group but preserves partial failures and unknown outcomes`
- `CacheMemberSelection > managed-group delete targets members; offline member stop is disabled`
- `ClusterResources > saved cache and mount actions address the saved resource ID`
- `ClusterResources > uncertain network outcomes stay visible and never silently repeat a mutation`
- `ClusterResources > mount creation keeps the selected machine, user, path and catalog defaults`
- `ClusterResources > HTTP pages without randomUUID still send a valid UUID request ID`
- `cacheMemberOptions > malformed member responses raise a useful Chinese error`

DTT：

- `tests/test_tool_commit_metadata.py` 收集失败：`ModuleNotFoundError: tests.test_smoke_cli`。
- `SmokeReportServerTest.test_owned_server_is_ready_before_start_returns` 与 `test_unknown_listener_is_not_killed`：本地 HTTP listener 未就绪。
- 一次专项运行中 `test_timeout_kills_descendant_even_when_group_leader_exits` 遇到测试代码检查 `/proc/<pid>/stat` 后、读取前进程退出的竞争；隔离复跑和完整专项复跑均通过，未将初次失败隐去。

## 后续人工验收

1. 更新平台和 DTT（包装脚本、镜像须同时含新接口），选空闲机器及挂载点。
2. 首轮选 fio + elbencho、60 秒、1 GiB，确认每工具独立数据集及顺序执行。
3. 检查每轮请求/实际时长，核对原生报告和平台指标；读测的数据准备不应算入测量时长。
4. 测试成功后清理、失败保留数据、取消、原参数重跑；确认只影响本任务子目录。
5. 换用旧 DTT 应得到升级提示，而不是成功执行一个忽略时长的任务。

## 自主决策

沿用已有机器/挂载点执行和性能报告，不额外创建文件系统。实施账本中的决定按顺序为：

1. 本期只对 fio/elbencho 提供统一时长/数据量引导，mdtest 保留原入口。若需要元数据性能引导，需要另补适配而不是套用数据量语义。
2. 主代理实现后端，DTT 代理在另一仓库并行实现，共享计时和报告接口经交叉验证。若接口遗漏，需跨仓库联调修正；本次真实本机联调已覆盖主路径。
3. 没有空闲集群，本次不部署、不做真实集群测试。代价是线上暂不可见，SSH、容器与真实挂载仍待部署后的人工验收。
4. 前端和 DTT 由独立文件范围的代理并行实现，由主代理验证集成边界。若模拟接口与线上数据不同，仍需真实网页验收；本次已完成模拟网页全流程。

若后续需要自动创建挂载的性能环境，可在此基础上扩展。功能代码提交：平台 `034ec6c`、`5f96557`、`f2f74c3`、`920bd23`、`b8f6553`；DTT `dd70a22`、`31c198f`、`950bcb6`、`c360b67`。

## 最终验证命令

后端从 `backend` 执行（辅助脚本仅连接隔离测试数据库）：

```bash
python3 /tmp/report-cache-tests-20261117.py tests/test_performance_runtime.py tests/test_performance.py tests/test_performance_matrix.py tests/test_performance_api.py tests/test_performance_dtt.py tests/test_performance_runner.py tests/test_performance_mdtest.py tests/test_performance_directory.py -q
```

本机跨仓库原生测试（新建临时目录，无远程连接）：

```bash
/tmp/dingofs-guided-functional.zMN5hR/platform/.venv/bin/python /tmp/guided-performance-local-smoke-20261117.py
```

前端使用本机可用的现代 Node 执行 `vitest run`、`tsc --noEmit`、`vite build`；本地 Vite 启动后执行 `playwright test tests/guided-performance.spec.ts`。浏览器测试全部模拟 API，无远端集群操作。

DTT 从其仓库执行：

```bash
python3 -m pytest -q tests/test_performance_plan.py tests/test_performance_tools.py tests/test_performance_runner.py tests/test_performance_cli.py tests/test_performance_report.py
bash -n dingofs-testsuite-tool entrypoint.sh
```
