# Machine Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 管理员配置机器 SSH 密码并手动刷新硬件信息，所有用户可查看结果。

**Architecture:** 在现有 inventory 上增加加密凭据和采集状态；独立 transport 执行固定只读命令，parser 产生结构化结果。短事务领取和提交采集令牌，网络期间不持有数据库锁。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL、Paramiko、cryptography、React、TypeScript、pytest、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-23-machine-inventory-design.md`

## Global Constraints

- 继续当前会话顺序实施，不使用子代理。
- 不连接真实机器、不重启当前网站、不改实际数据库或 .env。
- 保留所有已有未提交修改，尤其用户管理和 deploy/compose.yaml 中的 172.30.14.126 绑定。
- 首版 Linux；管理员写入并校验 CSRF，普通用户只读。
- 采集总时限默认 30 秒，输出上限 1 MiB；网络阶段不持有 inventory 全局锁。
- 密码不回显、不进日志/审计/高级 YAML；编辑留空保留，显式操作清除。
- PLATFORM_CREDENTIAL_ENCRYPTION_KEY 持久配置，缺失不得生成临时密钥。
- 每个任务先出现有意义的失败测试，再实现并验证；测试使用独立数据库与 SSH 替身。
- 在隔离副本中带入现有未提交代码；完成后核对基线哈希再同步明确文件。不得覆盖执行期间出现的用户新改动。
- 不将用户原有改动混入提交。实现交付时保留未提交供用户审阅；文档提交可单独处理。

## Review Focus

1. 密码带首尾空格必须原样保存（Task 1）。
2. hostname 的 DNS 查询阻塞也必须受总时限约束（Task 2）。
3. LVM/RAID/bind mount 容量不能重复加总（Task 3）。
4. 请求结束前修改 SSH 配置或撤销管理员权限不得提交旧快照（Task 4）。
5. 采集进程崩溃、浏览器刷新后不能永久卡在采集中（Task 4、5）。

## 文件边界与接口

新增 `inventory/credentials.py` 管理加解密；`inventory/ssh_transport.py` 负责连接与截止时间；`inventory/hardware.py` 定义命令和解析；`inventory/collection.py` 处理状态事务；`inventory/hardware_routes.py` 暴露刷新接口。前端新增 `features/inventory/MachineHardware.tsx` 展示快照，现有 InventoryPage 保持资源编辑入口。

通用返回类型：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int

@dataclass(frozen=True)
class SSHConfig:
    host: str
    port: int
    username: str
    password: str
    known_hosts: str

# transport.execute(config, commands, timeout_s, max_bytes)
# -> dict[str, CommandResult]
# parse_hardware(results) -> dict（schema_version=1）
# collect(config, transport) -> dict（status, hardware_info, warnings）
```

快照固定键为 cpu、memory、disks、filesystems、interfaces、rdma；不可获取项为 null 或缺项警告，不能假报为 0。采集状态 never、collecting、success、partial、failed；过期 collecting 对外返回 interrupted 并允许重试。

### Task 1: 密码存储、迁移和机器 API

**Files:** 修改 `inventory/models.py`、`schemas.py`、`service.py`、`routes.py`、`settings.py`、`backend/pyproject.toml`；新增 `inventory/credentials.py`、`backend/tests/test_machine_credentials.py`、`backend/migrations/versions/d7e142a893b1_machine_hardware.py`。

**Interfaces:** `encrypt_password(value: str, key: str) -> str`、`decrypt_password(value: str, key: str) -> str`；MachineInput 增加不 strip 的 ssh_password 和 clear_ssh_password，输出只增加 has_ssh_password。

- [x] 写失败测试，先覆盖加密和空白保留：

```python
def test_password_roundtrip_preserves_spaces():
    key = Fernet.generate_key().decode()
    ciphertext = encrypt_password(' secret ', key)
    assert ciphertext != ' secret '
    assert decrypt_password(ciphertext, key) == ' secret '
```

- [x] 运行 `PYTHONPATH=backend/src .venv/bin/pytest backend/tests/test_machine_credentials.py -q`，确认失败来自未实现能力。
- [x] 使用 Fernet 实现加解密；密钥缺失/格式错误/解密失败转为不含原始值的 Problem。明确新增密码与清除操作冲突时报 422。

```python
def encrypt_password(value: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(value.encode()).decode()
```

- [x] 修改模型：新增 ssh_password_ciphertext、hardware_info、last_attempt_info、last_attempt_at、last_success_at、collection_status、collection_error、collection_token、collection_expires_at。迁移 down_revision 为 c69f129b82a0，不修改旧记录。
- [x] 改为机器输出字段白名单；PATCH 合并只使用可编辑字段，密码独立处理，避免读取不存在的输出字段。旧有非机器资源不改变接口。
- [x] API 测试覆盖创建/修改/清除、留空、无密钥、错误密钥、权限、CSRF、明文/密文不出现在列表/详情/审计；迁移验证旧机器关联不变。运行上述定向测试至通过。

### Task 2: 有界 SSH Transport

**Files:** 新增 `inventory/ssh_transport.py`、`backend/tests/test_ssh_transport.py`；更新依赖锁定文件（沿用仓库现有锁定方式）。

**Interfaces:** `execute(config: SSHConfig, commands: dict[str,str], timeout_s: float=30, max_bytes: int=1048576) -> dict[str,CommandResult]`。

- [x] 先添加失败测试：

```python
def test_unknown_host_is_rejected(fake_ssh, ssh_config):
    fake_ssh.unknown_host = True
    with pytest.raises(CollectionError, match='host_key_unknown'):
        execute(ssh_config, {'cpu': 'lscpu -J'})
```

- [x] 实现 fake_ssh fixture，覆盖认证拒绝、变化的主机密钥、卡住的 DNS/认证/读取、输出超限和异常时关闭连接；运行 `pytest backend/tests/test_ssh_transport.py -q` 确认红灯。
- [x] 查阅 Paramiko 和 cryptography 官方文档，固定兼容 Python >=3.12 的依赖版本。用受监督子进程执行整个 SSH 工作，父进程单调时钟控制总时限、输出 IPC 大小与退出；超时 terminate/join，必要时 kill/join，避免 DNS 阻塞逃逸。

```python
remaining = deadline - time.monotonic()
if remaining <= 0:
    raise CollectionError('timeout')
# 父进程有界接收；子进程 finally 关闭 SSH client。
```

- [x] 子进程 SSHClient load_host_keys(config.known_hosts)，使用 RejectPolicy；connect 禁用 allow_agent/look_for_keys。只执行程序内固定命令，不拼接资源字段进 shell。
- [x] 定向测试通过，检查没有后台线程或子进程泄漏。

### Task 3: Linux 硬件采集与解析

**Files:** 新增 `inventory/hardware.py`、`backend/tests/test_hardware.py`、`backend/tests/fixtures/hardware/`（固定样例 JSON/文本）。

**Interfaces:** `COMMANDS: dict[str,str]`；`parse_hardware(results: dict[str,CommandResult]) -> dict`；`collect(config: SSHConfig, transport=execute) -> dict`。

- [x] 写解析失败测试，样例 disk 1000 bytes、partition 600 bytes 与 dm 600 bytes 只计物理盘 1000：

```python
def test_disk_total_excludes_partitions_and_dm(block_results):
    info = parse_hardware(block_results)
    assert sum(d['size_bytes'] for d in info['disks'] if d['type']=='disk') == 1000
```

- [x] 增加 CPU 核数未知、MemTotal 单位转换、多个 IP、网卡无 speed 权限、空 RDMA、IPv6、路径空格、无工具、损坏/超大 JSON、bind mount 重复的测试；运行 `pytest backend/tests/test_hardware.py -q` 确认失败。
- [x] 固定命令统一 `LC_ALL=C`，lscpu/lsblk/ip 优先 JSON，内存取 /proc/meminfo；df 使用 POSIX 字节口径换算，并独立关联 mountinfo。不依赖远端 Python或 sudo；RDMA 通过 sysfs 读取。对每段输出做类型、长度、数值范围检查。
- [x] 定义 CPU 型号、logical_cores、physical_cores；内存 total_bytes；磁盘 name/type/size_bytes/model/rotational；文件系统 source/mountpoint/total_bytes/available_bytes；网卡 name/mac/addresses/state/mtu/speed_mbps；RDMA device/port/interfaces。
- [x] 成功无缺项为 success，部分指标缺失为 partial，全空或连接错误为 failed；保留 warnings；运行定向测试至通过。

### Task 4: 刷新接口、并发和权限

**Files:** 新增 `inventory/collection.py`、`inventory/hardware_routes.py`、`backend/tests/test_machine_collection.py`；修改 `app.py`、机器序列化。

**Interfaces:** POST `/api/v1/machines/{id}/refresh-hardware` 接收 `base_revision: int`；`begin_collection(db,id,revision) -> (token, SSHConfig)`、`finish_collection(db,id,token,revision,result,actor)`。

- [x] 写失败测试证明失败保留成功快照：

```python
def test_failed_refresh_preserves_last_success(admin, machine_with_snapshot, failing_transport):
    old = machine_with_snapshot['hardware_info']
    r = admin.post('/api/v1/machines/'+machine_with_snapshot['id']+'/refresh-hardware',
                   json={'base_revision': machine_with_snapshot['revision']})
    assert r.json()['collection_status'] == 'failed'
    assert r.json()['hardware_info'] == old
```

- [x] 增加非管理员/CSRF、归档、重复请求、令牌超时重试、采集中修改配置、撤销权限、旧采集覆盖新采集、部分结果与旧快照区分测试；先运行 `pytest backend/tests/test_machine_collection.py -q` 确认失败。
- [x] 短事务行锁领取 token 与 expires_at，不在网络期间持有 db session；令牌领取不改变配置 revision。到期后允许新 token 替换旧 token。
- [x] 网络结束重新验证当前会话和管理员权限，校验 token、revision、archived；冲突时不写快照，旧 worker 不清除新 worker 状态。仅匹配 token 可以结束自己的采集。
- [x] success 更新 hardware_info 和 last_success_at；partial 写 last_attempt_info 并标示缺失项；failed 只更新本次状态与安全错误。提交有效结果后 revision 自增，返回完整安全机器视图；任何采集结果不写 physical_id。
- [x] 路由注册在通用 inventory router 之前；全部定向测试通过。

### Task 5: 机器页面与部署说明

**Files:** 修改 `frontend/src/features/inventory/InventoryPage.tsx`、`frontend/src/styles.css`、`backend/openapi.json`、`frontend/src/api/schema.ts`；新增 `MachineHardware.tsx`、`MachineHardware.test.tsx`、`frontend/tests/machine-hardware.spec.ts`；修改 `deploy/compose.yaml`、环境示例及 `docs/DEVELOPMENT.md`，新增 `docs/MACHINE_HARDWARE_ACCEPTANCE.md`。

**Interfaces:** MachineHardware 接收安全 Machine view、canEdit、onRefresh、refreshing；展示当前成功快照和最近一次采集状态。

- [x] 先写 UI 失败测试：

```tsx
it('普通用户只能查看', () => {
  render(<MachineHardware machine={machineFixture} canEdit={false}
    refreshing={false} onRefresh={vi.fn()} />);
  expect(screen.queryByRole('button', {name:'更新机器信息'})).toBeNull();
});
```

- [x] 增加密码输入不预填、清除显式动作、刷新禁用双击、超时恢复、失败仍显示旧数据、partial 标签、未知值显示“未知”测试；`npm test --prefix frontend -- --run` 确认红灯。
- [x] 机器编辑新增 password 类型输入，不要求填写。列表增加逻辑核数、内存、磁盘摘要；详情分 CPU/内存、磁盘/挂载点、网卡/RDMA 明细，使用 bytes 格式化函数，避免页面显示原始 JSON。
- [x] 刷新 POST 携带 CSRF 和 revision，结束重新读取机器；错误保留页面已显示信息。切换页面不保存密码到 localStorage/sessionStorage。
- [x] compose 为 API 注入加密 key 和 known_hosts 只读挂载；提供空 known_hosts 文件初始化方案，避免 Docker 将不存在源文件创建为目录。保留既有 HTTP 监听地址。文档说明指纹先核验、加密密钥备份、无密码时提示、只读采集，不修改用户 .env。
- [x] 重新导出 OpenAPI：`PYTHONPATH=backend/src .venv/bin/python -m dingofs_platform.export_openapi > backend/openapi.json`；`npm run generate-api --prefix frontend`。
- [x] 运行后端测试（TEST_DATABASE_URL 指向独立 loopback *_test 库）、前端测试、`npm run build --prefix frontend`；浏览器用 SSH 替身验收添加密码→刷新→详情→失败保留结果→普通用户只读。
- [x] `git diff --check`、审查密文输出泄漏与需求覆盖；清理本次临时服务。核对项目文件基线后同步变更，报告测试结果、部署步骤及未连接真实机器的验证边界。

## 执行交接

本计划依赖现有未提交的用户管理功能，不将其丢弃或重复实现。采用当前会话由同一执行者顺序完成。详细计划经用户确认后开始 Task 1；实施遇到不影响需求的常规选择自行处理，不逐任务请求许可。

执行完成：后端 61、前端 12、浏览器 4 项通过。无真实机器连接；代码保留未提交。硬件输出样例集中在 test_hardware.py 的 sample fixture 中，不单独散布 fixture 文件。
