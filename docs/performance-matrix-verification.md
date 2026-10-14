# 参数组合功能验证（2026-10-13）

本次功能已部署至 http://172.30.14.126:58080/#/performance 。

## 功能验收

- 后端定向测试42项通过：组合展开、重复值归一化、参数非法与数量上限、API快照与下发一致性、同工具多场景数据/报告隔离、失败继续、取消与超时、报告预算、权限及旧任务兼容。
- 前端组件4项通过；TypeScript与Vite生产构建通过。
- 部署后Playwright浏览器2项通过：实际多选生成8场景，编辑后预览失效；真实HTML报告在隔离iframe内显示平均带宽。
- 128机器SSH用户jenkins真实运行：fio 4场景（Direct/Buffered × 顺序读/写），elbencho 4场景（并发1/2 × Block 4KiB/64KiB），每场景2个1MiB文件、2轮。8/8通过，共16MiB数据保留在新建独立目录。
- 新目录自动创建、8个独立报告URL与iframe安全响应头均验证通过。
- 实跑任务：[8a1bc5d0-6b47-4c7f-b623-baf06c3d776a](http://172.30.14.126:58080/#/performance/8a1bc5d0-6b47-4c7f-b623-baf06c3d776a)。
- 这是小数据功能验收，不是性能基准。

## 全量回归的其他失败

全量后端运行639通过、23失败、2 teardown错误；全量前端376通过、6失败。
失败位于本次未修改的资源权限、主机信任、集群操作、挂载、远端SSH及资源UI模块。未把全量回归声称为通过；未扩大本次修改去处理这些模块。
其中两个帮助目录测试缺少容器挂载的docs/reference，补齐挂载后复核2/2通过；其余失败保留记录。原始完整日志在 `/tmp/platform-matrix-backend-tests.log` 与 `/tmp/platform-matrix-frontend-tests.log`。

后端失败项：

```text
FAILED tests/test_asset_permissions.py::test_members_create_and_only_manage_own_machine
FAILED tests/test_asset_permissions.py::test_config_read_shared_but_writes_and_topology_refresh_owned
FAILED tests/test_asset_permissions.py::test_owner_can_collect_hardware - Ass...
FAILED tests/test_cache_profile_parameters.py::test_complete_help_catalog - F...
FAILED tests/test_cluster_operations.py::test_foreign_actor_stale_and_expired_challenge
FAILED tests/test_cluster_operations.py::test_concurrency_limit_and_cancel_rejects_late_result
FAILED tests/test_cluster_operations.py::test_revoked_actor_during_execution_discards_result
FAILED tests/test_cluster_operations.py::test_unreadable_saved_credential_is_reported_as_failed_operation
FAILED tests/test_host_trust.py::test_missing_known_hosts_allows_safe_fingerprint_discovery
FAILED tests/test_host_trust.py::test_database_pin_has_priority_and_changed_key_contains_both_fingerprints
FAILED tests/test_host_trust.py::test_trust_lifecycle_and_replay_rejected - A...
FAILED tests/test_host_trust.py::test_stale_or_forged_challenge_is_rejected[expired]
FAILED tests/test_host_trust.py::test_stale_or_forged_challenge_is_rejected[edited]
FAILED tests/test_host_trust.py::test_stale_or_forged_challenge_is_rejected[archived]
FAILED tests/test_host_trust.py::test_stale_or_forged_challenge_is_rejected[forged]
FAILED tests/test_host_trust.py::test_permission_csrf_and_no_arbitrary_key_acceptance
FAILED tests/test_host_trust.py::test_address_change_does_not_reuse_trust - A...
FAILED tests/test_host_trust.py::test_real_ssh_first_contact_and_key_change_never_send_password
FAILED tests/test_machine_credentials.py::test_password_crud_never_discloses_secret
FAILED tests/test_mount_ports.py::test_mount_port_skips_occupied_default_and_updates_command
FAILED tests/test_mount_profiles.py::test_catalog_exactly_matches_client_help
FAILED tests/test_remote_e2e.py::test_http_list_read_download_through_real_ssh_worker
FAILED tests/test_remote_e2e.py::test_http_read_revalidates_symlink_after_listing
ERROR tests/test_remote_e2e.py::test_http_list_read_download_through_real_ssh_worker
ERROR tests/test_remote_e2e.py::test_http_read_revalidates_symlink_after_listing
```

前端失败项：

```text
FAIL  src/features/resources/CacheMemberSelection.test.tsx > managed-group delete targets members; offline member stop is disabled
FAIL  src/features/resources/ClusterResources.test.tsx > saved cache and mount actions address the saved resource ID
FAIL  src/features/resources/ClusterResources.test.tsx > uncertain network outcomes stay visible and never silently repeat a mutation
FAIL  src/features/resources/ClusterResources.test.tsx > mount creation keeps the selected machine, user, path and catalog defaults
FAIL  src/features/resources/ClusterResources.test.tsx > HTTP pages without randomUUID still send a valid UUID request ID
FAIL  src/features/resources/cacheMemberOptions.test.tsx > malformed member responses raise a useful Chinese error
```
