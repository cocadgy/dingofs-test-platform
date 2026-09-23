# Cluster Discovery and Status Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox (`- [ ]`) syntax for tracking. Preserve the user's inline execution preference; do not dispatch subagents.

**Goal:** 用户选择机器和 Linux 执行用户即可发现、批量导入集群，在全宽列表和独立详情中查看可信的 dingo 状态。

**Architecture:** 新增 clusters 模块承载纯解析、受控远程执行、发现/导入、状态快照和类型明确的 API。复用机器凭据、SSH 主机信任、权限审计与配置编辑；密码只存在于本次请求的短生命周期执行进程中。专用集群页面替代通用 InventoryPage 的集群登记入口。

**Tech Stack:** Python >=3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL >=16、Paramiko；React、TypeScript、Vite、Vitest、Playwright。保持当前锁定依赖，不为本轮引入消息队列或新 SSH 库。

**Spec:** [2026-09-23-cluster-discovery-design.md](../specs/2026-09-23-cluster-discovery-design.md)，已于本轮开始前获得用户书面继续指令。

## Global Constraints

- 使用目标用户登录环境的 PATH 查找工具；不要求填写 dingo 绝对路径。
- 远程连接始终使用机器资源中的 SSH 登录用户和既有凭据；需要时再切换执行用户。
- 每次命令独立指定 `dingo_cluster`；不执行 checkout，不修改默认集群。
- 本轮不实现部署、升级、启停、重启、清理或测试执行。
- 默认建议：发现 60 秒、状态 120 秒、输出上限 2 MiB、每台执行机器同时最多 2 个动作，均由服务端配置。
- 密码不放在 argv、环境变量、数据库、队列消息、审计字段、日志、异常文本或浏览器持久存储中。
- 已登记但未采集的集群可见；采集失败保留旧成功数据及其时间。
- 不连接真实 DingoFS 集群，不执行集群运维命令。只用隔离数据库、模拟 SSH/回环 SSH 和用户提供的样本验证。
- 不覆盖现有未提交文件、不自动部署、不推送。当前已有机器、用户、集群表单等大量未提交工作必须作为开发基线保留。

## Review Focus

1. sudo 自定义认证账号、提示分片及命令输出伪造 Password 字样：仅真实认证状态可请求/接收密码，Task 3 覆盖。
2. 登录初始化脚本改写 PATH、HOME、dingo_cluster 或打印 banner：验证身份、隔离协议输出、最后设置目标变量，Task 3 覆盖。
3. 两个平台用户并发刷新同一目标，期间机器凭据或集群绑定发生改变：租约/token/修订限制旧结果与密码重用，Task 4–5 覆盖。
4. `Up ... (unhealthy)`、空服务、单行截断、无法辨别的目录空格：不误判全部运行，Task 1 覆盖。
5. 旧数据中相同机器/用户/名称对应不同配置目录，和跨用户同名集群：保留 ID、允许同名、歧义需确认，Task 2、5 覆盖。

## 工作区与验证约定

项目：`/mnt/disk5/daigy/dingofs-test-platform`。执行开始先读设计全文、`git status --short` 与相关源码。按 using-git-worktrees 技能建立隔离工作区；基线必须包含当前未提交改动，不能仅从 HEAD 创建一个缺失既有功能的工作树。若受写权限限制，使用已验证的完整临时快照方法并记录原始文件 SHA256，结束逐文件检查冲突后同步。

以下命令在隔离工作区运行。Python 测试从 backend 目录执行：

```bash
TEST_DATABASE_URL=postgresql+psycopg://platform_test:local-test-only@127.0.0.1:55443/platform_discovery_test ../.venv/bin/pytest tests/test_cluster_parser.py -q
```

数据库必须为新建的本机测试容器，库名以 `_test` 结尾；测试夹具会删除重建表。浏览器使用另一个专用数据库，不与后端测试共享。不要复制真实 `.env`、SSH 密钥或 known_hosts 到测试快照。

每个任务按测试先行，先看到预期失败，再实现并运行相同命令。记录提交仅包含本任务文件；任务末尾给出建议提交消息，用户若要求统一提交则最后提交，禁止 `git add .` 混入旧工作。最终代码同步前检查源文件基线未变化。

## 文件与接口布局

新增后端 `backend/src/dingofs_platform/clusters/`：

- `schemas.py`：请求/响应、解析数据结构及错误枚举。
- `parser.py`：无 I/O 的 ls/status 解析。
- `models.py`：发现与远程动作持久化记录；不保存密码。
- `transport.py`：目标用户登录环境、sudo 认证、固定 dingo 命令及有界执行。
- `operations.py`：租约、动作状态、并发限额、挑战消费、取消与恢复。
- `service.py`：发现、导入、刷新及兼容绑定业务。
- `routes.py`：强类型集群 API，先于通用资产路由注册。

修改 `inventory/models.py` 的 Cluster 状态字段与身份约束；复用 `inventory/credentials.py`、`host_trust.py`，仅在确需共享连接基础时扩展 `ssh_transport.py`，保持原 execute 接口。

新增前端 `frontend/src/features/clusters/`：`ClusterPage.tsx`、`ClusterOverview.tsx`、`ClusterDetail.tsx`、`DiscoverClusters.tsx`、`OperationAuthDialog.tsx`。更新 App 集群入口和生成的 API 类型；保留 ConfigEditor。

---

### Task 1: 固定命令输出契约与纯解析器

**Files:**
- Create: `backend/src/dingofs_platform/clusters/__init__.py`, `schemas.py`, `parser.py`。
- Create: `backend/tests/fixtures/dingo/cluster-ls.txt`, `cluster-status-main.txt`（用户原始样本，去除聊天转义，不改真实路径）。
- Test: `backend/tests/test_cluster_parser.py`。

**Interfaces:**
- `parse_cluster_names(raw: str) -> list[str]`。
- `parse_cluster_status(raw: str, expected_name: str) -> ClusterSnapshot`。
- `ClusterParseError(code: str)`，code 为 `invalid_listing`、`invalid_header`、`target_mismatch`、`invalid_row`。
- `ServiceRow`：id、role、host、running_instances、expected_instances、container_id、status_text、state、ports、log_dir、data_dir、raft_dir。目录和容器空值为 None。
- `ClusterSnapshot`：cluster_name、cluster_kind、mds_addresses、tikv_addresses、services、role_counts、node_count、service_count、running_instances、expected_instances、state、parser_version。state 为 `running/degraded/stopped/unknown`。

- [ ] 写入用户样本，并先添加以下失败测试：

```python
from pathlib import Path
from dingofs_platform.clusters.parser import parse_cluster_names, parse_cluster_status

FIXTURES = Path(__file__).parent / 'fixtures' / 'dingo'

def test_user_sample():
    assert parse_cluster_names('  main-dingofs\n\ntest-dingofs\nmain-dingofs\n') == ['main-dingofs', 'test-dingofs']
    result = parse_cluster_status((FIXTURES / 'cluster-status-main.txt').read_text(), 'main-dingofs')
    assert (result.node_count, result.service_count) == (1, 10)
    assert (result.running_instances, result.expected_instances) == (10, 10)
    assert result.role_counts == {'coordinator': 3, 'store': 3, 'mds': 3, 'executor': 1}
    assert result.services[0].status_text == 'Up 19 hours'
    assert result.services[6].data_dir is None
    assert result.state == 'running'
```

- [ ] 执行 `pytest tests/test_cluster_parser.py -q`，确认失败原因是新接口不存在。
- [ ] 实现 Pydantic 类型、ANSI 去除、表头识别、完整多词状态提取；不按单空格固定切列。行匹配后验证实例数及列数，未知行报 invalid_row，空服务返回 unknown；原始输出由上层另存。
- [ ] 增加参数化测试：空 ls、长度/行数上限、CRLF、彩色输出、错误文字、名称含 shell 字符不执行、目标错配、失败进度提示、Exited、Up unhealthy、0/1、2/1、空服务、截断行、IPv6 地址、目录不能可靠分割时失败。配置集群名上限 120 字符、最多 1000 名称，超限显式报错。
- [ ] 重跑解析测试通过；建议提交 `feat: parse dingo cluster discovery and status output`。

### Task 2: 集群快照、同名身份与兼容迁移

**Files:**
- Modify: `backend/src/dingofs_platform/inventory/models.py`, `inventory/service.py`, `inventory/schemas.py`。
- Create: `backend/src/dingofs_platform/clusters/models.py`。
- Create: `backend/migrations/versions/f142a36d9be5_cluster_discovery.py`，接续 `f031925c8ad4`。
- Modify: `backend/migrations/env.py`（注册新模型）。
- Test: `backend/tests/test_cluster_discovery_migration.py`。

**Interfaces:**
- Cluster 增加 `binding_state`（legacy/verified/needs_confirmation）、`execution_home`、`resolved_dingo_path`、`status_snapshot`、`status_success_at`、`status_attempt_at`、`status_attempt_state`、`status_error_code`。
- 旧 dingo_path/config_dir/credential_ref 保留；新导入不要求客户端提供。解除集群 name 的全局唯一约束；验证入口仍使用现有 machine/user/config/name 联合身份，已验证默认配置的 config_dir 使用明确的内部配置身份，不猜未知 dingo 参数。
- `ClusterOperation` 字段：id、actor_id、kind（discover/status）、machine_id、machine_revision、target_user、cluster_id/cluster_revision（可空）、state、lease_token、lease_expires_at、result、error_code、started_at、finished_at、expires_at、challenge_digest、auth_account、auth_attempts。无任何密码字段。
- 动作状态：pending/running/needs_password/needs_trust/succeeded/failed/cancelled/interrupted；租约与结果过期均服务端判定。

- [ ] 在迁移测试中建旧 schema，写两个用户同名目标、共享入口、归档集群、关联环境、节点和 YAML 版本；升级后断言原 ID/配置/关联保持。

```python
# 在与现有 test_cluster_migration.py 相同的隔离 Alembic 测试夹具中：
with engine.connect() as db:
    row = db.execute(text('SELECT * FROM clusters WHERE id=:id'), {'id': old_cluster_id}).mappings().one()
    assert row['binding_state'] == 'legacy'
    assert row['status_snapshot'] is None
    assert row['config_dir'] == old_config_dir
    assert db.scalar(text('SELECT cluster_id FROM environments WHERE id=:id'), {'id': old_env_id}) == old_cluster_id
```

- [ ] 执行 `pytest tests/test_cluster_discovery_migration.py -q`，确认旧版本没有字段/同名约束不符。
- [ ] 实现迁移、模型和注册；Cluster 局部取消继承的 name unique，不影响机器/环境名称约束。旧数据不直接标记 verified，历史上下文不恢复为公开资源。
- [ ] 验证全新升级、旧库升级、`alembic check`；存在新同名数据时禁止无损条件不成立的 downgrade，明确错误而不删数据。验证原硬件与用户迁移测试仍通过。
- [ ] 建议提交 `feat: persist cluster discovery operations and status snapshots`。

### Task 3: 有界 SSH、用户切换与认证协议

**Files:**
- Create: `backend/src/dingofs_platform/clusters/transport.py`。
- Modify only as needed: `backend/src/dingofs_platform/inventory/ssh_transport.py`。
- Test: `backend/tests/test_cluster_transport.py`；复用 `test_ssh_transport.py` 的 fake channel/回环服务方式。

**Interfaces:**
- `ClusterCommand(kind: Literal['discover','status'], target_user: str, cluster_name: str | None)` frozen dataclass。
- `ExecutionIdentity(user: str, home: str, dingo_path: str)`。
- `ClusterCommandResult(identity: ExecutionIdentity, stdout: str, stderr: str, returncode: int)`。
- `AuthenticationRequired(account: str)`，`ClusterExecutionError(code: str)`。
- `execute_cluster(config: SSHConfig, command: ClusterCommand, *, password: str | None = None, timeout_s: int = 60, max_bytes: int = 2097152) -> ClusterCommandResult`；password repr/log 禁止，子进程监督覆盖 DNS/SSH/命令全过程。

- [ ] 新测试先断言命令构造不含切换密码、显式选择正确目标，登录脚本中的 banner 不混入解析文本；不同用户使用 sudo，同用户不调用 sudo。

```python
from dingofs_platform.clusters.transport import ClusterCommand

def test_only_fixed_actions_are_accepted():
    with pytest.raises(ValueError):
        ClusterCommand(kind='stop', target_user='root', cluster_name='main-dingofs')
```

- [ ] 执行 `pytest tests/test_cluster_transport.py -q` 确认预期失败。
- [ ] 先实现无密码路径：校验用户名；通过目标登录环境执行固定包装脚本，用随机标识界定身份/输出；ClusterCommand.__post_init__ 检查 kind/target_user，status 必须提供集群名而 discover 不接受集群名；校验 id、HOME、command -v dingo。发现清除 dingo_cluster，状态在登录初始化之后赋值。使用 shell 引用构造固定脚本，不把用户输入当命令。
- [ ] 实现受控认证：首次 `sudo -n -i -u` 失败，只有固定认证探测确认需要口令才返回认证挑战。认证探测使用 `sudo -S` 的随机提示及 `%p` 账号标识，读取分片完整提示，尚无口令时关闭 channel，不能无限等待。密码重试连接仍须等同一账号认证提示出现才通过 stdin 写入，命令输出阶段不再识别/响应提示。不启用回显，不把密码注入登录 shell。
- [ ] 对用户不存在、sudo 无授权/缺失、未知认证账号、SSH 认证失败、工具缺失、登录环境失败输出独立错误码；不回退到错误用户，不自动尝试 su。
- [ ] 使用 fake channel 精确覆盖提示分片、sudo targetpw/rootpw 对应账号、Password 伪输出、不同 nonce、错误口令、取消、输出上限和超时。回环 SSH 服务验证真实 stdin 流与退出码；不依赖开发主机真实 sudo 配置。
- [ ] 对密码哨兵值断言序列化结果、日志、异常、命令字符串均不含该值。重跑 `test_ssh_transport.py`、`test_machine_collection.py`、`test_host_trust.py`，确保硬件采集原 execute 签名与行为不变。
- [ ] 建议提交 `feat: execute dingo under the selected login user`。

### Task 4: 操作租约、密码挑战与状态快照

**Files:**
- Create: `backend/src/dingofs_platform/clusters/operations.py`。
- Modify: `backend/src/dingofs_platform/settings.py`, `clusters/schemas.py`。
- Test: `backend/tests/test_cluster_operations.py`。

**Interfaces:**
- `start_operation(request, actor, *, kind, machine_id, machine_revision, target_user, cluster_id=None, cluster_revision=None) -> ClusterOperation`。
- `run_operation(request, operation_id: str, *, password: str | None = None) -> dict`；仅固定动作，运行前验证租约与身份，transport 从 app.state.cluster_transport 注入或用 execute_cluster。
- `resume_operation(request, actor, operation_id: str, challenge: str, password: str) -> dict`；原子消费挑战，重新验证 actor/机器/集群修订。
- `cancel_operation(request, actor, operation_id: str) -> dict`；结果写入前验证 lease token。

- [ ] 基于现有 app/admin 测试夹具新增两个用户消费同一挑战、机器更新后旧结果到达、租约过期、重复恢复的失败测试。

```python
# 路由接入前直接调用 operations；接口接入后同例经 API 再验证。
# 每例使用 fixture 创建的 operation 和另一个 actor，不使用真实 SSH。
with pytest.raises(Problem) as denied:
    resume_operation(request, other_actor, operation.id, challenge, 'sentinel-password')
assert denied.value.status == 403
```

- [ ] 运行 `pytest tests/test_cluster_operations.py -q`，先失败后实现状态机。沿用项目 Problem.status/code/message 错误契约。
- [ ] 数据库事务/行锁分配 token、检查每机器两条活动租约；远程 I/O 在事务之外。将运行结果写回时匹配 actor、token 和绑定修订；已取消或过期不能覆盖。
- [ ] 无密码动作在受限本地执行线程启动，DB 保存状态供轮询；进程重启后过期 pending/running 标 interrupted。认证恢复由当前 HTTP 请求直接执行有界子进程，不把密码交给持久任务或线程等待队列。
- [ ] 挑战有效期 5 分钟、一次消费、最多 3 次错误认证；每次重试生成新挑战，绑定当前认证账号。发现结果有效期 15 分钟。服务端设置允许配置这些值，校验正整数及合理上限。
- [ ] host_key_unknown/changed 接入已有机器信任状态；管理员确认后重新发起并校验新修订，不复用旧密码挑战。普通成员只提示联系管理员处理信任。
- [ ] 成功状态经过 parser 目标校验才更新成功快照；失败只更新最近尝试。原始输出限制长度且过滤认证阶段输出；不会返回密码提示中的口令。
- [ ] 重跑并发、取消、过期、重放、权限、错误保持旧快照测试；建议提交 `feat: coordinate bounded cluster observations and authentication`。

### Task 5: 集群发现、幂等导入与强类型 API

**Files:**
- Create: `backend/src/dingofs_platform/clusters/service.py`, `routes.py`。
- Modify: `clusters/schemas.py`, `backend/src/dingofs_platform/app.py`, `inventory/routes.py`, `inventory/service.py`。
- Test: `backend/tests/test_cluster_discovery.py`, `test_cluster_status_api.py`。

**Interfaces (all under `/api/v1`):**

| Method / path | Body / purpose |
|---|---|
| POST `/cluster-discoveries` | `{machine_id, machine_revision, target_user}` → operation 202 |
| GET `/cluster-operations/{id}` | action state/result; private discovery/auth info only visible to actor |
| POST `/cluster-operations/{id}/authenticate` | `{challenge, password: SecretStr}` → updated operation |
| POST `/cluster-operations/{id}/cancel` | actor/admin cancellation, cannot consume another actor's credentials |
| POST `/cluster-discoveries/{id}/import` | `{names: list[str]}` from unexpired successful discovery → `{created, existing, needs_confirmation}` |
| GET `/clusters/overview` | bounded pages of compact table rows + total |
| GET `/clusters/{id}` | persisted metadata, successful snapshot, latest attempt, no secrets |
| POST `/clusters/{id}/refresh-status` | `{base_revision}` → operation 202 |
| PATCH `/clusters/{id}` | existing revision-protected name/archive edits; changing target requires explicit rediscovery/rebinding |

Register static discovery/status routes before generic `/{kind}` inventory routes. Remove generic unrestricted cluster create/target-edit path from browser flow; reject bypass of verified import in API while retaining controlled existing metadata edits. Rebinding consumes a current discovery result and base_revision; ambiguous legacy target does not run a status command until confirmed.

- [ ] Add failing tests with injected cluster_transport (return fixed identity and the Task 1 sample) for discovery→import→refresh; use existing machine/admin fixtures, no direct remote calls.

```python
r = admin.post('/api/v1/cluster-discoveries', json={
    'machine_id': machine_row['id'], 'machine_revision': machine_row['revision'], 'target_user': 'root'})
assert r.status_code == 202
# Controlled worker fixture waits for operation completion, with a test deadline.
result = admin.post(f"/api/v1/cluster-discoveries/{operation_id}/import", json={'names':['main-dingofs']})
assert result.status_code == 200
again = admin.post(f"/api/v1/cluster-discoveries/{operation_id}/import", json={'names':['main-dingofs']})
assert again.json()['existing'][0]['id'] == result.json()['created'][0]['id']
```

- [ ] Run both new test files, confirm expected missing-route failure.
- [ ] Implement import transaction and machine/user/config/name uniqueness; validate selected names belong to server discovery. Old matching cluster IDs reused only for unambiguous compatible bindings; otherwise needs_confirmation. Disappeared old entries remain registered.
- [ ] Trigger initial status operations after successful import. If authentication is needed again, show a new challenge; no backend password storage for automatic reuse. One short batch may reuse an in-memory password only if the same request/verified identity is still alive; do not design a credential cache.
- [ ] Add tests for cross-user same names, stale/foreign discovery, 1000-name bound, concurrent import, archived machine, legacy custom config ambiguity, inactive actor, member import forbidden/member fixed status allowed, arbitrary command injection rejected.
- [ ] Preserve YAML/config ownership and machine reference protection; archived clusters are not silently restored. Regenerate OpenAPI/schema after typed routes.
- [ ] Run discovery/status tests plus existing platform/config/cluster migration suites. Suggested commit `feat: discover import and observe clusters through typed APIs`。

### Task 6: 发现弹窗与用户认证交互

**Files:**
- Create: `frontend/src/features/clusters/DiscoverClusters.tsx`, `OperationAuthDialog.tsx`。
- Create: matching `.test.tsx` files。
- Modify: `frontend/src/api/schema.ts`（生成，不手改）。

**Interfaces:**
- `DiscoverClusters({onImported: (ids: string[]) => void, onClose: () => void})`。
- `OperationAuthDialog({operation, onCompleted, onCancel})`，operation 为生成的公开 DTO，密码始终只存在组件短期 state。
- 机器来源为现有机器列表 API；只展示活动资源，分页加载全部可选项。

- [ ] 用 RTL/vi.stubGlobal fetch 添加失败测试：只需机器与用户名，用户名默认 SSH 用户，查询列出两个名字，勾选导入不带 dingo 路径字段。

```tsx
render(<DiscoverClusters onImported={imported} onClose={closed} />);
fireEvent.change(screen.getByLabelText('执行机器'), {target: {value: machineId}});
expect(screen.getByLabelText('执行用户')).toHaveValue('zetyun');
expect(screen.queryByLabelText('dingo 工具路径')).toBeNull();
```

复用现有 fireEvent 工具，不新增 user-event 依赖。

- [ ] Run `npm test -- --run src/features/clusters/DiscoverClusters.test.tsx src/features/clusters/OperationAuthDialog.test.tsx` and confirm missing component failures.
- [ ] Implement idle/discovering/needs_password/needs_trust/results/importing/error states. Password dialog displays machine, SSH user, target user, auth account and action; clear secret on submit/cancel/unmount. No console logging or storage APIs for secrets.
- [ ] Test no-password happy path, exact auth-account prompt, denied-user/tool errors do not open password dialog, wrong password bounded retry, cancellation stops poll, expired challenge restarts discovery, stale async result after page leave ignored, existing rows nonduplicated.
- [ ] New data imports reset obscuring filters and give explicit links to imported cluster details. Existing hardware host-trust view can be linked for admin approval; return re-runs discovery after machine revision changes.
- [ ] Run unit tests and TypeScript build. Suggested commit `feat: discover clusters with conditional user-switch authentication`。

### Task 7: 集群概览与独立详情

**Files:**
- Create: `frontend/src/features/clusters/ClusterPage.tsx`, `ClusterOverview.tsx`, `ClusterDetail.tsx` plus tests。
- Modify: `frontend/src/App.tsx`, `features/inventory/InventoryPage.tsx`, `frontend/src/styles.css`。
- Reuse: `features/configuration/ConfigEditor.tsx`。

**Interfaces:**
- `ClusterPage({admin: boolean, onDirty: (v:boolean) => void})` owns `#/clusters`/`#/clusters/<id>` routes and table state。
- `ClusterOverview({state,onStateChange,onOpen,onDiscover})` consumes compact rows from `/clusters/overview`。
- `ClusterDetail({id,admin,onBack,onDirty})` fetches typed detail, triggers fixed refresh and reuses auth dialog.

- [ ] Add failing tests for ten overview columns, cross-page search, numerical/time ordering, absent snapshot visible, both users' same-name rows distinct, detail deep link and return-state retention.

```tsx
expect(screen.getAllByRole('columnheader')).toHaveLength(10);
await screen.findByRole('button', {name: '发现集群'});
fireEvent.click(screen.getByRole('cell', {name: '10/10'}));
await screen.findByRole('heading', {name: '服务实例'});
```

- [ ] Run new cluster page tests and confirm route/components missing failures.
- [ ] Implement list using same visual rules as machine overview, with cluster-specific state and generated types; do not refactor the functioning machine table merely to share code. Register cluster route separately in App, preserve authentication routing on refresh rather than reset to machines.
- [ ] Detail shows addresses, role counts, services, directory expansion/copy, raw text and last-attempt metadata; include ConfigEditor for active clusters. Red/amber states derive from parser; expose collection failures separately from process state.
- [ ] On entering detail show cache immediately and request a single refresh; StrictMode/re-render does not create unlimited operations. Automatic polls stop on terminal status/unmount; only manual retry after errors/auth cancellation. Batch refresh bounded by server, not one unbounded request per row.
- [ ] Test unhealthy/unknown status styling, old timestamp preserved after failure, long path copy, raw HTML escaped, multiple same-name detail selectors, legacy needs_confirmation, read-only member controls and dirty YAML route protection.
- [ ] Run cluster and existing machine frontend tests plus build. Suggested commit `feat: add full-width cluster overview and status details`。

### Task 8: 集成验收、部署说明与安全回归

**Files:**
- Create: `frontend/tests/cluster-discovery.spec.ts`, `backend/tests/test_cluster_secret_redaction.py`。
- Modify: `frontend/tests/platform.spec.ts`, `backend/tests/conftest.py`, `README.md`, `docs/DEVELOPMENT.md`, `docs/CLUSTER_MANAGEMENT_ACCEPTANCE.md`, `.env.example`（非秘密超时/上限设置）。
- Add: user sample variants in `backend/tests/fixtures/dingo/` if generated during parser tests。

- [ ] Update old registration browser/fixture flows to discovery/import; do not remove their configuration editing, optimistic-lock and reference-protection assertions.
- [ ] Browser fixture provides one machine with two target users, each two clusters including a same-name entry. Fake transport has deterministic no-password, password-required, denied-user and query-failure paths. No real remote machine credentials in fixtures.
- [ ] E2E: discover→conditional password→select/import→overview search/sort→detail service/directories/raw output→refresh failure preserves data→back retains state; refresh browser direct detail URL; member can read/refresh but cannot import/approve host keys.
- [ ] Secret sentinel test captures DB JSON/text, audit, HTTP responses and process args for all authentication outcomes. Assert plaintext secret never persisted/logged; reject submitting another user's/expired/changed-binding challenge.
- [ ] Run backend full suite in Python 3.12 deployment image against isolated Postgres; run frontend full unit suite/build and Playwright against a separate fixture database. Run `alembic check` and upgraded legacy-data fixture. Record exact passed counts and limitations; do not claim actual-cluster verification.

```bash
# In isolated workspace; TEST_DATABASE_URL points only to disposable local DB.
cd backend
../.venv/bin/pytest -q
cd ../frontend
npm test -- --run
npm run build
PLATFORM_E2E_URL=http://127.0.0.1:55174 npm run e2e
```

- [ ] Document two-field discovery, sudo/auth-account behavior, no saved temporary password, server limits, process-running vs business-health distinction, legacy rebinding rules and per-command dingo_cluster. Preserve current deployment IP and user-edited compose/.env settings.
- [ ] Self-review spec coverage and diffs; verify untouched machine/user features and absence of implicit cluster mutations. Sync only changed files with original SHA256 conflict detection; cleanup only this task's temporary processes/containers.
- [ ] Suggested final commit `test: cover cluster discovery and status lifecycle` if committing is authorized at execution time. Do not push or restart website. Final report links update instructions and states database migration is included.

## 计划自检与执行交接

覆盖映射：设计 1–3 → Task 1/5/6；设计 4 → Task 3/4/6；设计 5/10 → Task 2/5；设计 6 → Task 7；设计 7 → Task 1/5；设计 8 → Task 4/5/7；设计 9 → Task 3–7；设计 11 → Task 8。

实施顺序：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8。采用当前会话顺序实现，不使用子代理；每个任务完成测试后再进入下一任务。先确认本书面计划，然后使用 executing-plans 执行。
