# 基于已有环境的功能测试引导 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在四步引导中选择已有环境和精确用例，由测试框架准备、执行和收尾，在平台查看可信的进度及独立报告。

**Architecture:** 一个平台父任务包含按注册顺序执行的模块子任务，每个子任务调用一次单模块、单环境的 DTT。框架提供只读环境契约、共享运行上下文、资源归属及结构化事件；平台负责权限、持久互斥、幂等调度和结果展示。沿用现有代码，不另建测试执行器，不预先调用平台挂载引导。

**Tech Stack:** Python、DTT Bash/Docker 或 Podman、FastAPI/Pydantic、SQLAlchemy/Alembic/PostgreSQL、React/TypeScript/Vite、pytest/unittest、Vitest/Testing Library、Playwright；平台 Python >=3.12，前端 Node >=22.12.0。

**Spec:** [已批准设计](../specs/2026-11-10-guided-functional-existing-environments-design.md)。2026-11-10 用户确认；本计划待用户审阅和选择实施方式。

## Global Constraints

- 首期严格为 fault、quota、basic_file_operation、mount_subdir、trash、dirstat、hot_upgrade、xattr、warmup、client、cache_node、mds_manage；逐模块验证后才开放，不兼容的已选用例不得静默跳过。
- 四步顺序为“选择测试环境 → 选择模块和用例 → 运行设置 → 检查并启动”；不新增环境编辑、用户另选文件系统、二进制覆盖、无限循环或强制停止。
- 默认每模块超时 1440 分钟，范围 1–1440；实际子任务启动才计时。FAIL 重试默认 0，范围 0–5。
- 沿用原环境名和固定资源语义；禁止静默换集群、主机、用户、存储，禁止用宽泛前缀清理非本次资源。
- 保留失败现场时停止后续调度，剩余用例“未执行”；用例失败但无残留且恢复/收尾确认才可继续。命令行 daily 调度不改变。
- 取消/超时请求超过 600 秒仍无法确认结束，进入“需要处理”，继续监测、保留占用，不自动 kill 或强制卸载。
- 预检只读、不安装工具；安装单独确认。控制机只用 SSH 密码认证；所有远端目标和实际用户都需绑定与授权。
- 草稿显式恢复、离开提醒、左侧勾选框、机器名称/IP/用户展示保留；新引导不得自动打开历史完成任务。
- 报告按子任务隔离并受权限保护，不用全局 latest。源码版本、环境依赖、用例哈希冻结；日志、事件、快照、附件不得含秘密。
- 只提交本功能文件或 hunk，保留无关 dirty/untracked 内容，不 reset、stash 或批量提交用户工作树。

## Review Focus

1. base/storage 改变但叶 YAML 未变：旧预检和计划必须失效；任务 1、9 测试。
2. 并发提交、SSH 启动成功但响应丢失：只能执行一次，重启不能补发；任务 7、8、10 测试。
3. 同名前缀外部资源、创建成功后回执丢失：不误删、不假装无残留；任务 2–4 测试。
4. 超过 10000 行事件、半行写入、重复回放、秘密跨输出块：统计完整、不泄密；任务 5、10、11 测试。
5. 旧完成草稿、跨标签页更新、单环境历史、report 404：不串任务，历史可读，失败明确；任务 7、12、13 测试。

---

## 仓库和文件责任

| 前缀 | 根目录与责任 |
| --- | --- |
| P | `/mnt/disk5/daigy/dingofs-test-platform`：平台、迁移、前端、发布文档 |
| B | `P/backend/src/dingofs_platform`：后端模块，后续 B 路径均展开为此目录 |
| F | `P/frontend/src`：前端组件 |
| D | `/mnt/disk5/daigy/dingofs-testsuite-tool`：DTT 包装和容器入口 |
| I | `D/dingofs-integration-test`：独立 Git 子模块，测试解析和执行 |

框架新增文件均在 `I/src/test_runner/`：functional_contracts.py（只读描述）、functional_capabilities.py（模块约束）、runtime_context.py（共用上下文）、resource_journal.py（归属）、functional_events.py（事件）、functional_redaction.py（秘密）。不把全部逻辑继续堆入 run_tests.py。

平台新增 `B/functional/{contracts.py,source_bridge.py,submission.py,preflight.py,scheduler.py,event_reader.py,results.py,reports.py}` 和共享 `B/operations/{__init__.py,models.py,leases.py}`。现有 routes/manager/transport/remote_runner 调用这些模块；新引导与旧六步自建环境向导分离。

## 开工和验证约定

执行前使用 using-git-worktrees 建立隔离工作树；核对 P、D、I 的 HEAD、分支、gitlink、暂存区及未跟踪文件。I 必须独立提交，再更新 D 的指针。已有 functional 草稿和三份迁移尚未提交，不等同于 HEAD 基线。逐项核对重叠，只把必需的已有改动带到隔离工作树并记录来源；无法分离时先说明，不批量搬入其他功能。三仓库引用指向同一组工作树，禁止误用 `/home/jenkins/dgy/github/dingofs-integration-test` 的另一份克隆。

以下命令只在实施时运行。框架新测试使用临时 YAML 和拒绝真实 SSH 的替身；不能把历史 tests/test_env_setup.py 或 tests/test_env_cleanup.py 全文件当作只读验证，它们含环境/SSH 调用。DTT 测试用 fake Docker，不执行 dtt daily。

后端命令 cwd 为 P/backend；`TEST_DATABASE_URL` 必须是专用 localhost/127.0.0.1 且库名以 `_test` 结尾的库，fixture 会建删测试表，绝不能用生产数据库。前端命令 cwd 为 P/frontend，`npm test -- --run` 只执行一次。每任务先确认指定失败来自新行为缺失，而非依赖或数据库未准备，再实现并复跑。

每次提交先 `git diff --check`，然后 `git add -- <本任务明确文件>`、检查 `git diff --cached` 再 commit；禁止 `git add .`。已有草稿产生的额外必需文件必须先审阅再纳入。旧失败和新增失败分开记录。

## 跨任务数据契约

- `Target={role,host,user,mutates}`，user 不含密码。`EnvironmentDescriptor={env_name,source_manifest,digest,mds_addresses,targets,client_count,cache_count,storage_type,programs,directories,modules,issues}`，数量允许 null；manifest 为受信根相对路径→SHA256，含完整继承链、storage 和选中 YAML。`ModuleCapability={available,reasons,required_tools,impacts,fixed_resources}`。框架用 dataclass，平台 contracts.py 定义同字段的 Pydantic 类型，通过 JSON 传输；纯检查不实例化有副作用的 executor。
- `RuntimeContext={parent_id,child_id,module,env_name,env,source_manifest,approved_targets,journal,events}`，env 一次解析并禁止 repr/JSON 泄密。`ResourceRecord={id,kind,cluster,host,user,name,path,port,owned,phase,remote_identity}`；phase=intent/active/retained/removed/unknown，只清理身份仍匹配且确认 owned 的资源。
- 事件 v2：`version,parent_id,child_id,seq,time,module,type,stage,case_path,attempt,host,user,data`；不适用字段可空，seq 单子任务持久递增。stage=preflight/setup/cases/cleanup/report；type 至少包含 stage_started/stage_finished/case_started/case_finished/resource_changed/suite_finished/cancelled。
- `ModuleSelection={module,environment_profile_id,environment_profile_revision,cases:[relative_path]}`；`RunSpec={name,cluster_id,module_plans:[ModuleSelection],catalog_digest,retries,timeout_minutes}` 是预检输入，不需要 token。`RunInputV2` 在 RunSpec 上增加 `version:2,idempotency_key,preflight_token,confirmed_impacts:[digest],draft_id?,draft_revision?`。模块去重并按框架注册顺序规范化。`NormalizedSubmission` 为规范化的 RunSpec 加 `request_digest,environment_snapshots,case_hashes` 和可选提交控制字段，由 submission.py 定义；request_digest 不包含 token、幂等键、草稿标识或确认摘要。
- `PreflightResult={token,request_digest,expires_at,checks,required_confirmations,can_start}`；token 绑定用户/请求/源，600 秒有效，启动仍重验。故障影响以摘要确认；首期拒绝需要高风险 opt-in 的用例，不接受客户端任意字符串开启。
- `LeaseRequest={key,mode}`，mode=shared/exclusive；`LeaseDecision={acquired,conflicts}`，`Conflict={key,owner,reason}`；`VerificationEvidence={owner,remote_ended,recovery_ok,verified_resources,remaining_resources,observed_at}`。均定义于 operations/leases.py，不允许客户端直接提交“已复核”证据。
- 父状态 queued/running/cancelling/unknown/needs_attention/success/failed/cancelled/timed_out；子任务另有 not_run。`ChildResult={case_counts,attempts,suite_errors,cleanup_status,recovery_status,retained_resources,report_status,returncode}`，counts=selected/passed/failed/skipped/not_run，report_status=pending/ready/failed/missing。`DispatchDecision={action,child_id,reason}`，action=wait/launch/poll/finish；`EventBatch={records,next_offset,file_identity}`。

## 依赖顺序

1→2→3、4→5→6 建立框架契约；7→8 建立平台持久模型，可在独立文件上并行。9 依赖 1、6、7、8；10 依赖 5–9；11 依赖 10；12 依赖 7、9；13 依赖 10–12；14 验证整体。相同文件不能由两个实现者同时编辑；接口变更须更新所有消费任务。

### Task 1 框架只读环境描述与兼容契约

**Files:** Create `I/src/test_runner/functional_contracts.py`、`functional_capabilities.py`、`I/tests/test_functional_contracts.py`；Modify `I/src/config/env_parser.py`、`environment_contracts.py`，不改变普通 CLI 解析结果。

**Interfaces:** Produces `inspect_environment(source_root: Path, env_name: str, modules: dict[str,list[str]]) -> EnvironmentDescriptor`，`module_capability(module: str, env: EnvironmentConfig, cases: list[dict]) -> ModuleCapability`。`python3 -m src.test_runner.functional_contracts` 从 stdin 读 JSON，只输出脱敏 JSON。

- [ ] **Step 1** 写 `test_inherited_sources_and_secret_allowlist`：manifest 含 base/storage/所选 YAML，改 base 后 `assert before.digest != after.digest`，`assert 'fixture-secret' not in serialized_descriptor`；`test_contract_inspection_has_no_io_side_effect` 中 SSH、目录创建、外部命令替身一经调用即失败。
- [ ] **Step 2** 在 I 运行 `python3 -m pytest -q tests/test_functional_contracts.py`，预期新接口缺失失败。
- [ ] **Step 3** 复用 parser 的 base/list/hosts/storage 规则，定义 12 模块最低能力、required_environment/contract 检查和额外目标。重复名、循环、缺 base、未知目标及未接入模块给不可运行原因；实例数量按真实展开规则。异常不打印原 YAML 秘密。
- [ ] **Step 4** 同命令通过；参数化覆盖 12 模块，其余 available=false；固定环境不匹配、继承/存储变更、逃逸路径均拒绝。
- [ ] **Step 5** 提交本任务文件：`git commit -m "feat: describe functional environment contracts without side effects"`。

### Task 2 普通模块共用上下文与精确清理

**Files:** Create `I/src/test_runner/runtime_context.py`、`resource_journal.py`、`I/tests/test_functional_owned_lifecycle.py`；Modify `I/run_tests.py`、`src/test_runner/test_suite.py`、`models.py`、`src/config/env_setup.py`、`env_cleanup.py`。

**Interfaces:** Consumes Task 1；Produces `build_runtime_context(parent_id: str, child_id: str, module: str, env: EnvironmentConfig, descriptor: EnvironmentDescriptor, root: Path) -> RuntimeContext`；`ResourceJournal.record(record: ResourceRecord) -> None`、`retained() -> list[ResourceRecord]`。原 env_setup/env_cleanup 增加 keyword-only `runtime_context: RuntimeContext|None=None`，保留原返回类型。

- [ ] **Step 1** 写 `test_setup_executor_cleanup_share_env_object`：`assert setup_env is executor_env is cleanup_env`；`test_cleanup_does_not_delete_sibling_or_external_fs`：owned=false 和同前缀外部 FS 不在删除命令中；`test_create_reply_lost_is_unknown`：回执丢失留下 unknown，不能盲删。
- [ ] **Step 2** I 运行 `python3 -m pytest -q tests/test_functional_owned_lifecycle.py`，预期上下文/台账断言失败。
- [ ] **Step 3** 先持久记录 intent，再执行并核验远端身份写 active。动态 FS/cache/mount 加子任务唯一标识且同步所有引用；部分 setup 失败仍有台账。平台 cleanup 不重解析、不按前缀删除；清理错误写入 SuiteResult，不只打印日志。无 context 的旧调用保留。
- [ ] **Step 4** 新测试通过，再运行 `python3 -m pytest -q tests/test_run_tests_lifecycle.py tests/test_functional_cancellation.py`；使用完整替身验证普通 7 模块和旧调用。
- [ ] **Step 5** 提交：`git commit -m "fix: scope functional setup and cleanup to task owned resources"`。

### Task 3 固定文件系统与故障恢复

**Files:** Create `I/tests/test_functional_fixed_adapters.py`；Modify `I/run_tests.py`、`src/config/env_setup.py`、`ssh_client.py`、`src/client_test/mixins/mount_ops.py`、`cache_group_ops.py`、`src/fault_test/executor.py`、`src/test_runner/runtime_context.py`、`functional_capabilities.py`。

**Interfaces:** Consumes RuntimeContext/ResourceJournal；Produces `verify_runtime_target(context: RuntimeContext, host: str, user: str, operation: str) -> None`。既有固定资源 owned=false，新创建才 owned=true；原环境名和恢复 hook 不变。

- [ ] **Step 1** 写 `test_existing_fixed_fs_is_never_owned_or_deleted`：原名不变且 owned=false；`test_unapproved_case_target_rejected_before_command`：`assert remote.call_count == 0`；`test_fault_cancel_still_recovers`：取消仍执行恢复并记录结果。
- [ ] **Step 2** I 运行 `python3 -m pytest -q tests/test_functional_fixed_adapters.py`，预期归属/目标校验失败。
- [ ] **Step 3** 接通 ensure 固定 FS、用例内挂载/缓存、外部故障工具目标和恢复。SSH 最低层及本地控制/外部 chaos 参数构建均校验目标，不仅保护 setup；不能枚举的目标和高风险用例预检拒绝，不自动启用 external chaos，不重命名专用固定资源。
- [ ] **Step 4** 同命令通过，增加新建固定 FS、身份变化、恢复失败阻止后续和旧无 context 调用断言。
- [ ] **Step 5** 提交：`git commit -m "feat: bind client and fault lifecycles to functional task ownership"`。

### Task 4 缓存节点热升级和 MDS 专用生命周期

**Files:** Create `I/tests/test_functional_special_adapters.py`；Modify `I/src/cache_node_test/executor.py`、`src/hot_upgrade_test/executor.py`、`src/mds_manage_test/executor.py`、`src/test_runner/functional_capabilities.py`。

**Interfaces:** Consumes RuntimeContext 和 Task 3 目标校验；Produces 各模块 cleanup_status/recovery_status/retained_resources。cache_node 的 before/after_suite 仍自管资源；hot_upgrade 升级目标按用例语义，不与初始二进制混淆。

- [ ] **Step 1** 参数化 `test_special_module_journals_its_resources` 验证三模块真实资源记录；`test_after_suite_error_blocks_success`：`assert suite.suite_errors > 0`；`test_cache_partial_create_does_not_stop_external_member` 验证外部 member 不在停止命令内。
- [ ] **Step 2** I 运行 `python3 -m pytest -q tests/test_functional_special_adapters.py`，预期记录/错误传播失败。
- [ ] **Step 3** 接通成员 ID、升级前后挂载/进程身份和 MDS 恢复证据；未确认的 intent/恢复标 unknown/retained，不按组前缀释放。所有模块约束在副作用之前检查。
- [ ] **Step 4** 同命令通过；各模块伪 executor 覆盖正常、失败、取消、部分启动；逐模块审查差异，验证通过才标 capability 可用。
- [ ] **Step 5** 提交：`git commit -m "feat: track specialized functional module cleanup and recovery"`。

### Task 5 完整事件取消结果和源头脱敏

**Files:** Create `I/src/test_runner/functional_events.py`、`functional_redaction.py`、`I/tests/test_functional_events.py`、`test_functional_redaction.py`；Modify `I/src/test_runner/functional_plan.py`、`test_suite.py`、`models.py`、`allure_reporter.py`、`I/src/config/logger.py`、`I/run_tests.py`。

**Interfaces:** Produces `EventWriter.emit(type: str, stage: str, **data) -> int`，`collect_runtime_secrets(env: EnvironmentConfig) -> tuple[str,...]`，`redact_value(value: object, secrets: tuple[str,...]) -> object`。SuiteResult 增加 cancelled/cleanup_status/recovery_status/retained_resources，旧字段保留；事件 v2 与 case-plan v1 分别版本化。

- [ ] **Step 1** 写 `test_every_attempt_and_stage_has_identity`：每 attempt/阶段记录且末次只计一次；`test_cancel_with_rc_zero_is_not_complete`：未执行不通过；`test_secret_absent_from_logs_events_and_attachments`：密码、S3/RADOS 密钥和 run_as_user 密码不在任何产物或异常中。
- [ ] **Step 2** I 运行 `python3 -m pytest -q tests/test_functional_events.py tests/test_functional_redaction.py tests/test_functional_cancellation.py`，确认新行为失败。
- [ ] **Step 3** 事件落盘后报告状态，恢复不重置 seq，保留半行边界；只在安全边界取消并执行必要恢复。日志、事件、Allure attach_data/attach_file 写出前脱敏，不能只遮盖网页；无法安全处理的附件不公开并提示。规范化秘密不放入事件 data。
- [ ] **Step 4** 同命令通过，补充并发 emit、重开序号、半行恢复、清理错误退出状态和原始 Allure 文件秘密扫描。
- [ ] **Step 5** 提交：`git commit -m "feat: emit complete redacted functional lifecycle events"`。

### Task 6 DTT 不可变运行时能力和封装

**Files:** Modify `D/dingofs-testsuite-tool`、`entrypoint.sh`、`tests/test_functional_plan_cli.py`、`test_functional_environment_cli.py`；Create `D/tests/test_functional_runtime_cli.py`；Modify `B/tool_packages/automatic_helper.py`、`automatic.py`、`P/scripts/prepare-tool-bundle.py`、`P/backend/tests/test_functional_binary_package.py`。

**Interfaces:** Produces `dtt --functional-capabilities --format json` → `{version:2,features,files,image_id,source_manifest}`，只读验证文件/本地镜像，不 pull/run。features 必含 exact_case_plan_v1/runtime_context_v1/owned_cleanup_v1/lifecycle_events_v2/cancel_boundary_v1/inspection_v1。新增 `--functional-context <absolute-json>` 传父子 ID、冻结摘要和核验目标，无密码；原 --case-plan 不变。

- [ ] **Step 1** 写 `test_missing_capability_fails_before_launch`：`assert docker_invocations == []`；`test_context_and_manifest_are_read_only_mounts`；`test_image_and_base_digest_change_rejected`。包测试断言所有框架新增文件、依赖配置、清理代码纳入清单，不能只查入口文件。
- [ ] **Step 2** D 运行 `PYTHONPATH=tests python3 -m unittest test_functional_runtime_cli test_functional_plan_cli test_functional_environment_cli test_integration_exit_status`；后端运行 `python3 -m pytest -q tests/test_functional_binary_package.py`，预期新断言失败。
- [ ] **Step 3** 按原相对路径封装内容寻址树，固定 image_id/文件 SHA；执行不跟随 current/latest。每子任务输出隔离，容器 setup 前再次校验。自动和离线包共用 manifest，公开元数据不含预置秘密；不得破坏性能工具路径。
- [ ] **Step 4** 两侧命令通过；增加空格路径、缺文件、错架构、旧能力、未确认更新及旧 int 回归，均用 fake Docker。
- [ ] **Step 5** I 已提交后，D 更新已核实的 gitlink 及本任务文件，分别提交 `feat: package immutable functional runtime capabilities` 和平台 `feat: deploy versioned functional runtime bundles`，不夹带性能/AI 修改。

### Task 7 平台父子模型与幂等提交

**Files:** Create `B/functional/contracts.py`、`submission.py`、`B/operations/__init__.py`、`models.py`、`P/backend/migrations/versions/7b1c9e4a602d_functional_module_runs.py`、`P/backend/tests/test_functional_submission_v2.py`；Modify `B/functional/models.py`、`schemas.py`、`routes.py`、`P/backend/migrations/env.py`。

**Interfaces:** Produces `normalize_submission(payload: RunInput|RunSpec|RunInputV2, catalog: dict, environments: dict[str,dict]) -> NormalizedSubmission`、`create_run(db: Session, actor: User, request: NormalizedSubmission) -> FunctionalRun`。environments 为服务端按环境 ID 查询且核对版本的脱敏快照，不接收客户端自报快照。新增 FunctionalModuleRun/FunctionalPreflight/FunctionalEvent/FunctionalResource/OperationLease；子任务唯一 (run_id,module)/(run_id,position)，事件唯一 (child_id,seq)，幂等唯一 (creator_id,idempotency_key)。OperationLease 为可重入、共享/排他请求提供持久记录，不用一条排他 unique key 冒充读写租约。

- [ ] **Step 1** 写 `test_same_key_returns_same_parent_and_changed_body_conflicts`：同请求同 ID、变内容 409；`test_legacy_single_env_normalized_but_history_readable`；`test_two_module_environments_are_distinct_snapshots`，确认两环境原名/哈希分别冻结。
- [ ] **Step 2** 后端运行 `python3 -m pytest -q tests/test_functional_submission_v2.py`，预期 schema/模型缺失失败。
- [ ] **Step 3** 原 FunctionalRun 作父，新模型保存上述契约；旧历史无子任务时只读适配。迁移承接已核实的 2f6d6db8c141，去掉阻止同集群排队的旧 active unique index，实际启动由 Task 8 互斥。新任务 deadline 在子任务启动设置，旧记录保留。运行入口先 feature flag 关闭，待 Task 10 接通；核实三份未跟踪前置迁移，不重复造表。
- [ ] **Step 4** 同命令通过；专用测试库验证迁移/历史/并发唯一约束，测试越界、模块重复、哈希变化、权限和 CSRF；不操作线上数据库。
- [ ] **Step 5** 提交：`git commit -m "feat: persist idempotent functional parent and module runs"`。

### Task 8 持久占用和跨功能冲突

**Files:** Create `B/operations/leases.py`、`P/backend/tests/test_operation_leases.py`；Modify `B/functional/submission.py`、`manager.py`、`B/performance/routes.py`、`manager.py`、`B/tool_packages/routes.py`、`B/resources/views.py`、`execution.py`；增加 `P/backend/tests/test_performance_api.py`、`test_tool_package_api.py`、`test_resource_api.py` 的冲突用例。

**Interfaces:** Produces `acquire_leases(db: Session, owner: str, requests: list[LeaseRequest]) -> LeaseDecision`、`check_conflicts(db: Session, requests: list[LeaseRequest], owner: str|None=None) -> list[Conflict]`、`release_verified(db: Session, owner: str, evidence: VerificationEvidence) -> None`。cluster:<id> 和真实写目标 machine:<id> 排他；runtime:<machine_id> 运行共享/安装排他，按 key 排序后原子获取。

- [ ] **Step 1** 写 `test_two_workers_only_one_acquires_same_targets`：一方 acquired；`test_unknown_and_retained_keep_leases`：重启/TTL 不释放；`test_verified_cleanup_can_release_exact_retained_owner`：结束证据及精确复核缺一不可。
- [ ] **Step 2** 后端运行 `python3 -m pytest -q tests/test_operation_leases.py`，预期租约接口缺失失败。
- [ ] **Step 3** 对排序后的 key 使用稳定 64 位摘要的 PostgreSQL transaction advisory lock，锁内检查/写入持久租约，解决“冲突行尚不存在”的并发竞态；全部获取或全部回退。统一先取租约 advisory 锁、再按 ID 取 inventory/业务行锁，避免 API 间反向锁序。queued 不提前独占，同 owner 重入，unknown 不能按 TTL 抢占。性能/工具/资源写操作提交和执行前均检查；只读继续，已结束任务精确残留清理有受限例外。
- [ ] **Step 4** 新测试和三个 API 的新增用例通过；同机器不同环境仍冲突，纯共同控制机不独占无关集群，runtime 共享读与更新写冲突，复核失败不释放；不得宣称能锁住平台外 Jenkins。
- [ ] **Step 5** 提交：`git commit -m "feat: coordinate functional resources with durable operation leases"`。

### Task 9 环境摘要与只读预检

**Files:** Create `B/functional/source_bridge.py`、`preflight.py`、`P/backend/tests/test_functional_preflight.py`；Modify `B/functional/environments/importer.py`、`service.py`、`validation.py`、`routes.py`、`B/functional/routes.py`、`B/settings.py`、`P/backend/pyproject.toml`、`requirements.lock`、`P/deploy/compose.yaml`、`P/backend/tests/test_functional_environment_importer.py`。

**Interfaces:** Consumes Tasks 1、6、8；Produces `inspect_source(source_root: Path, env_name: str, modules: dict[str,list[str]]) -> EnvironmentDescriptor`（受限子进程调用框架纯检查）、`preflight(db: Session, actor: User, request: NormalizedSubmission) -> PreflightResult`。新增 `POST /api/v1/functional/preflight`；提交检查 token/input 摘要，启动仍重验。

- [ ] **Step 1** 写 `test_preflight_has_zero_remote_mutations`：fake SSH 只接受许可只读命令；`test_base_drift_invalidates_token`；`test_cache_fault_and_mds_hosts_require_permission`：额外目标未授权不放行；`test_changed_input_cannot_reuse_token`。
- [ ] **Step 2** 后端运行 `python3 -m pytest -q tests/test_functional_preflight.py tests/test_functional_environment_importer.py`，确认新断言失败；原固定 41 文件/100 环境测试改为临时源和完整枚举对照，不假定部署永不增加环境。
- [ ] **Step 3** 预置 importer 消费框架描述，删除重复继承算法；旧自建环境接口保留。桥接只能执行受信源码，设超时/输出上限；将 I 的 PyYAML 解析依赖纳入平台锁文件，不导入有日志/远端副作用的 executor。检查集群、所有主机/用户、版本、工具、二进制、路径、端口和占用，生成 600 秒 token/影响摘要。
- [ ] **Step 4** 同命令通过；模板、缺配置/凭据/工具、认证不支持、权限撤销、源消失、包错版本、未确认安装均有明确原因；异常也不泄密。排队启动重新核验，不能用有效 token 绕过权限或版本变化。
- [ ] **Step 5** 提交：`git commit -m "feat: preflight existing functional environments without mutations"`。

### Task 10 顺序编排事件游标与取消状态

**Files:** Create `B/functional/scheduler.py`、`event_reader.py`、`results.py`、`P/backend/tests/test_functional_scheduler.py`、`test_functional_event_reader.py`；Modify `B/functional/manager.py`、`transport.py`、`remote_runner.py`、`routes.py`。

**Interfaces:** Produces `advance_parent(db: Session, run_id: str) -> DispatchDecision`、`read_events(path: Path, offset: int) -> EventBatch`、`evaluate_child(snapshot: dict, events: list[dict], remote_state: dict) -> ChildResult`。每次只 dispatch 一个子任务；Transport 请求含 child_id/launch_token/runtime_manifest，远端按 child_id 持久化，重启只查询。

- [ ] **Step 1** 写 `test_response_lost_does_not_relaunch_child`：`assert launches == 1`；`test_retained_failure_marks_remaining_not_run`；`test_timeout_starts_at_child_start_and_grace_is_600_seconds`；`test_reads_12000_events_with_partial_tail_and_duplicates`：全部 12000 条保留，半行不推进游标。
- [ ] **Step 2** 后端运行 `python3 -m pytest -q tests/test_functional_scheduler.py tests/test_functional_event_reader.py`，预期调度/游标行为失败。
- [ ] **Step 3** 子任务独立 root/output/plan/context/cancel，单模块/原 env_name 调用。启动 token/进程身份持久化，重复 bootstrap 不再启动。逐批持久去重事件，不依赖末尾 10000 行；截断/轮转不能静默丢数据。取消/到期等待安全边界，600 秒未确认进入 needs_attention；SSH 失联 unknown，不失败重跑。事件完整、无 suite 错误、恢复/清理确认及远端结束才成功。
- [ ] **Step 4** 新测试通过；增加启动前取消零副作用、恢复失败、attempt 最终计数、用例通过但清理失败、剩余未执行；替身回归 `tests/test_functional_runner.py tests/test_functional_environment_runner.py tests/test_functional_lifecycle.py`。
- [ ] **Step 5** 提交：`git commit -m "feat: orchestrate functional module runs with recoverable state"`。

### Task 11 模块报告重跑与残留复核

**Files:** Create `B/functional/reports.py`、`P/backend/tests/test_functional_reports.py`、`test_functional_rerun_v2.py`；Modify `B/functional/routes.py`、`submission.py`、`report_redaction.py`、`transport.py`、`B/resources/execution.py`、`B/operations/leases.py`。

**Interfaces:** 新增 `GET /api/v1/functional/runs/{run_id}/modules/{child_id}/report/{path:path}`；`rerun_parent(db: Session, actor: User, run_id: str, failed_only: bool, idempotency_key: str) -> FunctionalRun`；`verify_retained_resources(db: Session, actor: User, run_id: str) -> VerificationEvidence`。旧 report 路径只读旧任务自己的产物。

- [ ] **Step 1** 写 `test_module_report_never_falls_back_to_latest`：缺失具体 404；`test_report_path_and_owner_guard`；`test_rerun_failed_only_excludes_not_run_and_source_drift`：只含明确失败用例，源变 409；`test_chunked_secret_not_downloadable`：跨输出块秘密和附件无泄露。
- [ ] **Step 2** 后端运行 `python3 -m pytest -q tests/test_functional_reports.py tests/test_functional_rerun_v2.py`，预期新断言失败。
- [ ] **Step 3** 报告根限定 child，检查授权、路径和符号链接；报告失败与测试结果分开。重跑重验权限/版本/占用，生成新父 ID，不直接接旧挂载。既有管理操作处理残留后只读复核精确身份，再释放；不能相信客户端“已处理”。源头脱敏加代理防护，无法保证安全的二进制附件不公开。
- [ ] **Step 4** 同命令通过；原版本丢失、越权、旧历史、恶意路径、复核失败、unknown/取消均不能自动重跑；一个模块报告缺失不影响其他已完成报告。
- [ ] **Step 5** 提交：`git commit -m "feat: expose isolated functional reports and verified reruns"`。

### Task 12 四步引导草稿和导航

**Files:** Create `F/features/getting-started/GuidedFunctionalFlow.tsx`、`GuidedFunctionalFlow.test.tsx`、`functional/EnvironmentStep.tsx`、`CaseStep.tsx`、`RunOptionsStep.tsx`、`PreflightStep.tsx`、`useFunctionalDraft.ts`；Modify `F/App.tsx`、`features/getting-started/GettingStartedPage.tsx`、`features/functional/CaseSelector.tsx`、`types.tsx`、`FunctionalPage.tsx`、`functional.css`、`B/functional/drafts.py`、`P/backend/tests/test_functional_wizard_drafts.py`。

**Interfaces:** `GuidedFunctionalProps={userId:string,onNavigate:(hash:string)=>void,onDirty:(dirty:boolean)=>void}`，`GuidedFunctionalFlow(props: GuidedFunctionalProps)` 接 App 现有守卫；configuration 白名单为 `{kind:'existing-environments',version:2,cluster_id,default_environment_id,module_plans,name,retries,timeout_minutes}`，不存 preflight token。旧缺 kind/version 草稿按 legacy 六步读，不自动转换。显式恢复 `#/start/functional?draft=<id>`，提交带 draft_id/revision。

- [ ] **Step 1** 写 `test_new_start_does_not_restore_completed_run`、`test_module_environment_required_when_incompatible`、`test_defaults_1440_minutes_zero_retries`、`test_navigation_confirmation_before_leaving`；多个环境不预选首项、checkbox 左置、不出现新建 FS/二进制输入。后端加草稿越权、版本冲突、非法字段/秘密测试。
- [ ] **Step 2** 前端运行 `npm test -- --run src/features/getting-started/GuidedFunctionalFlow.test.tsx`，后端运行 `python3 -m pytest -q tests/test_functional_wizard_drafts.py`，确认新断言失败。
- [ ] **Step 3** 四步复用 CaseSelector，展示真实名称/IP/用户及摘要；修改输入即废弃预检。安装通过 tool-jobs 显式确认并重检。草稿字段白名单防止 run_as_user 密码绕过简单 key 检查，冲突不覆盖；新入口只询问恢复未提交草稿。菜单/内部返回走 onDirty，结果页离开不停止远端任务。
- [ ] **Step 4** 两侧新测试通过；回归 `npm test -- --run src/features/getting-started/AppNavigation.test.tsx src/features/getting-started/GettingStartedPage.test.tsx src/features/functional/FunctionalWizard.test.tsx src/features/functional/FunctionalPage.test.tsx`；旧六步、新四步分开显示。
- [ ] **Step 5** 提交：`git commit -m "feat: guide functional tests through existing environments"`。

### Task 13 模块结果页面和历史兼容

**Files:** Create `F/features/functional/ModuleRunDetail.tsx`、`RunDetail.test.tsx`；Modify `F/features/functional/RunDetail.tsx`、`RunList.tsx`、`types.tsx`、`FunctionalPage.tsx`、`functional.css`。

**Interfaces:** Consumes Task 10 ChildResult 和 Task 11 模块报告。types.tsx 定义 `MachineIdentity={machine_id,name,ip,user}`、`ModuleRunView={id,module,env_name,state,stage,execution_targets:[MachineIdentity],events:[FunctionalEventV2],started_at,finished_at,result:ChildResult}`；FunctionalEventV2 与上述事件协议同字段。后端详情接口用冻结的机器身份补充 execution_targets，不能用当前改名后的机器覆盖历史身份。组件为 `ModuleRunDetail({runId,child}: {runId:string;child:ModuleRunView})`。unknown/needs_attention 继续轮询，未知数量不用虚构百分比。

- [ ] **Step 1** 写 `test_setup_has_machine_ip_user_before_cases`、`test_final_attempt_counts_once`、`test_remaining_modules_not_run`、`test_child_report_failure_is_not_pass_link`、`test_legacy_run_without_children_still_renders`；报告 URL 含正确父子 ID，取消中不能显示已停止。
- [ ] **Step 2** 前端运行 `npm test -- --run src/features/functional/RunDetail.test.tsx`，预期旧单任务渲染不满足新断言。
- [ ] **Step 3** 父汇总、模块展开阶段/attempt/清理/恢复/残留资源，按钮提供日志、各自 Allure 和重跑。未执行不计通过，suite 错误单列，报告状态独立；404 不跳旧链接，长名称不引入页面横向溢出。旧无 children 任务用只读适配展示。
- [ ] **Step 4** 同命令通过，再运行 `npm test -- --run src/features/functional` 和 `npm run build`；覆盖角色权限、零结果、历史任务和报告未生成。
- [ ] **Step 5** 提交：`git commit -m "feat: show per module functional progress results and reports"`。

### Task 14 整体闭环与受控发布

**Files:** Create `P/frontend/tests/guided-functional.spec.ts`、`P/backend/tests/test_functional_end_to_end.py`、`P/docs/operations/guided-functional-release.md`；Modify `P/deploy/compose.yaml`、`api.Dockerfile`、`B/app.py`、`settings.py`，只接本功能开关/运行时；核对 P、D、I 发布提交。

**Interfaces:** `PLATFORM_GUIDED_FUNCTIONAL_ENABLED` 默认 false，迁移/运行时/契约匹配才开放新入口和提交；历史读取保留。发布指南记录三仓库提交、不可变包/镜像、迁移 revision 及回退方法，不保存凭据。

- [ ] **Step 1** 写伪远端闭环：两环境→预检→提交→两个单模块请求→事件→各自报告，断言未批准安装零请求、失败保留时第二任务未启动、重启不重复启动。Playwright 使用本地测试平台和路由/传输替身，不连接 126/真实 SSH。
- [ ] **Step 2** 后端 `python3 -m pytest -q tests/test_functional_end_to_end.py`；前端 `npm run e2e -- tests/guided-functional.spec.ts`，先记录缺失闭环的失败，服务器 URL 必须为隔离本地环境。
- [ ] **Step 3** 接通 feature flag、路由/worker、固定源树/依赖和 readiness 能力检查；写升级演练/回退指南。做整分支独立审阅，12 模块各自适配门槛未满足时不能只改 UI 标为可用。
- [ ] **Step 4** 闭环、各任务定向测试、frontend build 通过后，在专用测试库演练迁移。先提交/推送 I，再 D 的 gitlink，再 P；遵循批准的发布分支，不擅自强推或切 main。发布前确认活动/unknown 任务可兼容处理，否则暂不切换；备份数据库、保留旧包。逐条执行 `docker compose -f deploy/compose.yaml build api web`、`docker compose -f deploy/compose.yaml run --rm migrate`、`docker compose -f deploy/compose.yaml up -d api web`；readiness 通过后在部署配置显式启用 PLATFORM_GUIDED_FUNCTIONAL_ENABLED 并重新加载服务，回读入口/权限/历史报告。失败关闭入口、恢复兼容版本，不删除任务数据或旧运行时。
- [ ] **Step 5** 明确授权且无冲突后，在 126 用网页运行一个普通最小用例，核实创建/挂载/执行/清理/Allure；专用模块和故障注入另定范围，不能夹带服务停止或大规模任务。证据写发布指南，提交 `docs: record guided functional release and acceptance`；缺真实验收权限时说明“本地闭环通过，真实环境待验收”，不声称全量验证。

## 计划覆盖自查

| 设计要求 | 负责任务 |
| --- | --- |
| 原环境、继承、专用约束、全部目标权限 | 1、3、4、9 |
| 共用配置、归属、精确清理、失败现场 | 2、3、4、10、11 |
| 阶段、attempt、取消、超时、无假成功 | 5、10、13 |
| 不可变来源、能力检查、确认安装 | 6、9、12、14 |
| 幂等、排队、互斥、恢复不重发 | 7、8、10 |
| 草稿、离开提醒、四步与机器展示 | 7、12、13 |
| 独立报告、重跑、秘密保护 | 1、5、6、9、11、13 |
| 历史、迁移、发布及验收边界 | 7、12、13、14 |

主执行者交付计划前自行检查覆盖、步骤可执行性、接口一致性、五类 Review Focus 和篇幅；代理只提供源码事实，不代替自查。实施结束另做整分支代码审阅。

## 实施方式待选择

推荐逐任务代理实施并审阅：框架资源归属/恢复与平台状态/并发都可能影响真实集群，每项通过审阅后再推进。无共享文件的实现或独立调查可以并行，不让两个代理同时修改同一生命周期。也可由主代理在当前会话顺序实施，最后独立整分支审阅。用户审阅本计划并选择方式后再开始代码实施。
