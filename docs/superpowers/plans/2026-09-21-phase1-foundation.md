# DingoFS Test Platform Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本会话由主执行者顺序完成，不使用子代理。步骤用复选框记录。

**Goal:** 交付可登录、可管理资产和环境、可编辑并发布配置版本的真实网站；不连接真实集群。

**Architecture:** 同仓库前后端分离。API 持久化到 PostgreSQL；配置服务拥有 YAML 编辑与版本逻辑，前端只提交明确操作。发布配置不执行远端操作。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL >=16、ruamel.yaml；React、TypeScript；pytest、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-21-dingofs-test-platform-design.md` 与 `docs/superpowers/specs/2026-09-21-dingofs-test-platform-technical-design.md`。

> 执行状态：Task 1–6 已完成。测试与模块文件按体量合并，计划中的示例命令以实际合并测试覆盖；映射和实施裁定见 [执行记录](../../PHASE1_EXECUTION.md)，结果见 [验收记录](../../PHASE1_ACCEPTANCE.md)。

## Global Constraints

- 第一版测试默认复用现有集群；本阶段只实现基础网站和配置管理，不执行测试或运维。
- Python 3.12、PostgreSQL 16 或以上；依赖及前端 Node LTS 在 Task 1 验证兼容并锁定。
- 普通成员可读，资产和配置修改限管理员；未探测集群显示 unknown。
- 发布配置不调用 dingo；不复制已有测试项目代码。
- YAML 最大 1MiB，拒绝重复键、自定义标签、多文档、alias/merge key。
- 不自动创建默认账号，不把秘密写进源码、错误响应、审计或版本差异。
- 本地测试仅使用临时数据库、fixture 和临时文件，不访问已有 DingoFS 环境。

## Review Focus

1. 被环境引用的机器不能被归档，且并发请求不能绕过关系约束（Task 3）。
2. YAML 错误与修订冲突不能导致用户本地编辑丢失（Task 4、5）。
3. 两条相同管理上下文记录不能绕过未来的上下文锁（Task 3）。
4. 伪造角色、CSRF 或失效 cookie 不能修改资产（Task 2、6）。
5. 数据库和 API 重启后配置版本及资产不丢失（Task 6）。

## Task 1：可启动的 API、数据库与前端入口

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/dingofs_platform/{app,settings,db}.py`。
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/tests/{conftest,test_health}.py`。
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/{main,App}.tsx`。
- Create: `.env.example`, `deploy/compose.yaml`, `deploy/{api,web}.Dockerfile`, `deploy/nginx.conf`。

**Interfaces:** `create_app(settings: Settings) -> FastAPI`；`GET /health/live` 返回进程存活；`GET /health/ready` 在数据库不可用时返回 503。Settings 从环境读取，缺失必要配置启动失败。

- [x] RED：添加以下 API 测试以及关闭临时数据库后 readiness=503 的测试。

```python
def test_liveness(client):
    response = client.get('/health/live')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
```

- [x] 执行 `cd backend && pytest tests/test_health.py -q`，确认接口缺失导致失败。
- [x] 添加应用工厂、数据库会话和 Alembic；创建独立测试数据库 fixture，禁止测试默认使用生产 DATABASE_URL。
- [x] 创建最小前端路由和中文导航，未实现页面不显示成功数据；反向代理 `/api` 到 API。
- [x] 锁定依赖，提交 lock 文件；不得把本机已有依赖当作部署依赖来源。
- [x] 验证健康接口、前端构建和本地 Compose；记录启动命令与测试数据库销毁方式。逐文件审查本任务变更。

## Task 2：登录、会话与权限

**Files:**
- Create: `backend/src/dingofs_platform/auth/{models,schemas,service,routes,dependencies,cli}.py`。
- Create: `backend/migrations/versions/0001_auth.py`, `backend/tests/test_auth.py`。
- Create: `frontend/src/features/auth/{LoginPage,SessionProvider}.tsx`, `frontend/src/api/client.ts`。

**Consumes:** Task 1 的应用工厂和数据库会话。
**Produces:** `current_user(request) -> User`、`require_admin(user) -> User`；`POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`GET /api/v1/auth/me`。前端统一请求封装处理失效会话和 CSRF。

- [x] RED：使用真实数据库写入 admin/member 测试账号，不替换权限依赖。

```python
def test_logout_revokes_cookie(auth_client):
    old_cookie = auth_client.cookies.get('session')
    assert auth_client.post('/api/v1/auth/logout').status_code == 204
    auth_client.cookies.set('session', old_cookie)
    assert auth_client.get('/api/v1/auth/me').status_code == 401
```

- [x] 添加密码错误、禁用账号、会话过期、伪造 role 输入和缺少 CSRF 的用例；执行 `pytest tests/test_auth.py -q`，确认失败。
- [x] 实现密码哈希、随机会话 token、摘要存储、过期和撤销；密码登录不允许用户指定角色。
- [x] 实现交互式 `python -m dingofs_platform.auth.cli create-admin`；不得通过命令行明文参数传入初始密码。
- [x] 实现登录页和会话恢复，API 返回 401 时清理前端状态；测试日志不打印密码或 cookie。
- [x] 重跑 auth/health 测试，验证管理员创建和登录流程，逐文件审查变更。

## Task 3：机器、集群、管理上下文和环境

**Files:**
- Create: `backend/src/dingofs_platform/inventory/{models,schemas,service,routes}.py`。
- Create: `backend/src/dingofs_platform/audit/{models,service}.py`。
- Create: `backend/migrations/versions/0002_inventory.py`, `backend/tests/test_inventory.py`。
- Create: `frontend/src/features/inventory/{MachinesPage,ContextsPage,ClustersPage,EnvironmentsPage}.tsx`。

**Consumes:** 会话依赖、数据库事务。
**Produces:** 技术设计中的四组 CRUD 接口；PATCH 使用 `base_revision`，冲突返回 409。GET 响应包含 revision；列表使用 items/total。

- [x] RED：建立 machine → cluster/context → environment 的真实数据库 fixture。

```python
def test_referenced_machine_cannot_be_archived(admin_client, linked_inventory):
    machine = linked_inventory['machine']
    response = admin_client.patch('/api/v1/machines/' + machine['id'], json={
        'base_revision': machine['revision'], 'archived': True})
    assert response.status_code == 409
    assert response.json()['code'] == 'resource_in_use'
```

- [x] 添加 member 修改返回 403、重复上下文返回 409、端口越界返回 422、未知机器关联返回 422、两次相同 revision 更新第二次冲突的测试。
- [x] 执行 `pytest tests/test_inventory.py -q` 确认失败；实现模型、迁移、白名单输入和事务性关系检查。
- [x] 列表页面提供搜索、分页和详情；管理员有登记/编辑入口，普通成员只读；集群状态明确为尚未探测。
- [x] 审计保存动作和脱敏差异；credential_ref 不允许替代为任意上传私钥。
- [x] 运行 inventory/auth 测试以及前端页面测试，确认刷新后资源仍存在，逐文件审查变更。

## Task 4：YAML 草稿、表单更新、配置版本

**Files:**
- Create: `backend/src/dingofs_platform/configuration/{models,schemas,yaml_document,service,routes,redaction}.py`。
- Create: `backend/migrations/versions/0003_configuration.py`。
- Create: `backend/tests/{test_yaml_document,test_config_versions}.py`。

**Consumes:** owner 资产与管理员权限。
**Produces:** 技术设计的 draft/publish/versions/diff API。
`update_form(text: str, updates: dict[str, object], document_kind: str) -> str` 只更新环境字段白名单；原生拓扑没有已验证 schema 时不提供猜测的表单字段。

- [x] RED：验证注释和高级字段保留。

```python
def test_form_update_keeps_advanced_fields():
    text = '# retained\nfilesystem: old\nadvanced:\n  custom_flag: true\n'
    updated = update_form(text, {'filesystem': 'new'}, 'platform-environment')
    assert '# retained' in updated
    assert 'custom_flag: true' in updated
    assert 'filesystem: new' in updated
```

- [x] 添加重复键、alias、merge key、自定义标签、多文档、超过 1MiB 和过期修订号测试；执行两份测试确认失败。
- [x] 实现 ruamel.yaml round-trip 文档处理和明确的 form field whitelist；解析错误转换成不含秘密的行列错误。
- [x] 在数据库事务中比较 revision、更新草稿及追加审计；publish 重新校验并复制成不可变版本，计算内容摘要。
- [x] 测试发布之后再修改草稿不会改变旧版，版本差异脱敏，发布不会调用外部命令。
- [x] 验证原生拓扑显示“语法已校验，工具未校验”，而非“可部署”；逐文件审查变更。

## Task 5：配置编辑页面和真实 API 联动

**Files:**
- Create: `frontend/src/features/configuration/{ConfigEditor,FormFields,YamlEditor,VersionHistory,ConfigDiff}.tsx`。
- Create: `frontend/src/features/configuration/ConfigEditor.test.tsx`。
- Create: `frontend/src/api/schema.ts`（由 OpenAPI 生成，不手抄接口）。

**Consumes:** Task 4 配置 API；revision 是后端版本，dirty text 是浏览器尚未保存的文本。
**Produces:** 环境/集群详情中的配置页、版本列表和差异页。

- [x] RED：使用前端测试模拟 API 返回非法 YAML 错误，断言编辑器文本保留。

```tsx
it('keeps unsaved YAML after validation fails', async () => {
  const view = await openEditorWithApiFixture('invalid-yaml');
  await view.replaceYaml('filesystem: [');
  await view.save();
  expect(view.yamlValue()).toBe('filesystem: [');
  expect(view.publishButton()).toBeDisabled();
});
```

测试 helper `openEditorWithApiFixture` 放在该测试文件，渲染真实 ConfigEditor，仅替代 HTTP 返回，不替代编辑/保存逻辑。

- [x] 增加 409 冲突不覆盖本地编辑、切换视图保留高级字段、普通成员没有修改入口、发布按钮不执行运维的行为测试。
- [x] 执行 `cd frontend && npm test -- --run` 确认失败，再实现页面状态和 API 调用。
- [x] 未保存离开页面提示；成功保存才更新 revision；服务端错误显示具体原因，不清空表单。
- [x] 显示“保存草稿”“发布配置版本”两个动作，并说明二者不修改远端集群。
- [x] 运行前端测试、类型检查和构建；不使用空成功回调或假数据替代后端。

## Task 6：端到端验收与启动说明

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/tests/platform.spec.ts`。
- Create: `docs/DEVELOPMENT.md`, `docs/PHASE1_ACCEPTANCE.md`。
- Modify: `README.md`, `deploy/compose.yaml`。

**Consumes:** 已完成的前后端和数据库。
**Produces:** 可复现的本地启动方式和第一阶段验收证据。

- [x] 先写端到端流程：管理员登录 → 登记机器 → 登记管理上下文/集群 → 关联环境 → 表单修改 → YAML 高级字段编辑 → 发布 → 查看版本差异。

```tsx
test('published configuration survives reload', async ({page}) => {
  await createEnvironmentAndPublishThroughUi(page, 'e2e-environment');
  await page.reload();
  await expect(page.getByText('e2e-environment', {exact: true})).toBeVisible();
  await expect(page.getByText('版本 1', {exact: true})).toBeVisible();
});
```

helper 在 `frontend/tests/platform.spec.ts` 中通过 UI 完成真实 API 操作，不直接插入假发布结果。

- [x] 增加普通成员修改被拒、CSRF 被拒、非法 YAML 保留、revision 冲突、归档关系约束的端到端验收。
- [x] 在独立临时 PostgreSQL 中跑迁移和完整后端测试；跑前端测试、类型检查、构建和 Playwright。
- [x] 重启 API 和数据库后验证资产/版本保留，终止临时数据库时 readiness=503；不使用生产数据做检查。
- [x] 文档列明环境变量、创建管理员、迁移、启动、备份/恢复、测试命令，以及第一阶段尚未开放的测试执行和集群运维入口。
- [x] 汇总第一阶段验收证据，再进入下一阶段计划；不得宣称整个平台第一版已经完成。

## 计划自检

产品设计中的登录、资产、关系、表单/YAML、版本和差异在 Task 1–6 覆盖。实际集群导入、测试目录、调度、Worker、执行、报告和运维属于后续阶段，未被悄悄删除，见技术设计的阶段划分。

本计划的 API 字段、错误码和文件边界以前述技术设计为准。每个任务先失败测试再实现；只对本阶段代码进行本地验证。提交代码前应明确提交范围，不能将其他仓库未提交改动带入本项目。
