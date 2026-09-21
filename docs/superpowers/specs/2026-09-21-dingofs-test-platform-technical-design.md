# DingoFS 测试平台：技术设计补充

日期：2026-09-21。状态：待审阅；补充第一版产品设计，不表示应用已经实现。

## 架构选择

采用同仓库的 React + TypeScript 前端、Python FastAPI API 和 Python Worker，PostgreSQL 保存任务、资产、配置及调度状态。SQLAlchemy 管理数据访问，Alembic 管理迁移。前后端由同一入口提供服务，运行日志采用可续传 SSE，测试产物使用独立存储卷。

第一版不引入 Redis/Celery，避免任务队列与数据库资源预留形成两套状态源。API 不在请求线程内启动测试。Worker 主动向 API 领取任务，只接受服务端生成的不可变计划，不直接接受浏览器命令。

前后端分离有利于后续增加任务日志、表格筛选和 YAML 编辑。服务端渲染单体能减少初期构建配置，但长期交互仍需大量前端状态处理。独立微服务会增加部署与事务边界，第一版不采用。

运行基线 Python 3.12、PostgreSQL 16 或以上；前端使用实施时验证兼容的 Node LTS。具体依赖和镜像版本在初始化任务中锁定，不使用浮动 latest 作为可复现实验版本。

## 仓库布局

```text
backend/
  pyproject.toml
  src/dingofs_platform/
    app.py                 API 应用装配
    settings.py            环境配置
    db.py                  数据库会话
    auth/                  登录、会话、角色
    inventory/             机器、集群、环境和管理上下文
    configuration/         YAML 草稿、版本、差异
    audit/                 审计事件
    catalog/               测试目录（第二阶段）
    jobs/                  计划、任务和步骤（第二阶段）
    scheduling/            资源预留与领取（第二阶段）
    adapters/              测试工具与 dingo（后续阶段）
    worker/                心跳、执行和恢复（第二阶段）
  migrations/
  tests/
frontend/
  src/features/            按登录、资产、集群、环境、配置、任务划分
  src/api/                 生成的 API 类型与请求封装
  tests/
deploy/                    Compose、反向代理及配置模板
docs/                      设计、计划和使用说明
```

按职责分模块，第一阶段只创建实际需要的目录；不提前生成空适配器和假执行接口。

## 第一阶段：网站基础与配置管理

交付可启动的网站，包含本地账号登录、管理员/普通成员权限、机器登记、管理上下文登记、集群登记、环境关联，以及表单/YAML 草稿编辑、发布版本和差异查看。

集群登记不等于实际导入：第一阶段集群健康状态固定显示“尚未探测”，不填充虚构的在线实例。真实导入、连通性检测、测试提交和运维按钮在对应后续能力接通前不开放。

表单先覆盖已经定义的平台环境字段，例如资源关联、文件系统名称、挂载根目录、工具路径。dingo 原生拓扑先作为高级 YAML 保存；只有拿到实际 schema 和测试夹具之后，才增加对应部署参数表单，不把平台环境字段误写进 dingo 拓扑。

### 数据模型

所有业务记录使用 UUID、创建/更新时间和修订号。对外不暴露数据库内部连接信息。

| 模型 | 核心字段及约束 |
|---|---|
| User | username 唯一、password_hash、role=admin/member、disabled |
| Session | token_hash、user_id、expires_at；登出撤销 |
| Machine | name 唯一、address、ssh_port、ssh_user、credential_ref、physical_id 可选、tags、maintenance；地址/端口规范化 |
| ManagementContext | machine_id、os_user、dingo_path、config_dir、credential_ref；相同机器/用户/config_dir 唯一，防止多个记录绕过上下文锁 |
| Cluster | name、context_id、external_name、management_scope；同一上下文下 external_name 唯一；无探测前 observed_state=unknown |
| ClusterMachine | cluster_id、machine_id、role、managed；关系唯一，可区分外部依赖 |
| Environment | name 唯一、cluster_id、enabled；客户端关系通过 EnvironmentMachine 关联 |
| EnvironmentMachine | environment_id、machine_id、role；禁止引用不存在或已归档资产 |
| ConfigDraft | owner_kind=environment/cluster、owner_id、document_kind、yaml_text、revision |
| ConfigVersion | owner、version、immutable_yaml、sha256、author、created_at；已发布版本不可原地修改 |
| AuditEvent | actor、action、entity、outcome、request_id、脱敏后的变更摘要 |

credential_ref 仅登记预置凭据的引用，第一阶段不实现网页上传密钥。记录删除采用归档；被环境或集群引用的机器不能归档。环境与配置修改均用修订号检测并发编辑。

### 第一阶段 API 合同

统一前缀 `/api/v1`。响应错误格式为 `{"code":"revision_conflict","message":"配置已被其他人修改","details":{}}`。

- `POST /auth/login`、`POST /auth/logout`、`GET /auth/me`：登录、登出和身份；没有默认账号或硬编码密码。
- `GET/POST /machines`、`GET/PATCH /machines/{id}`；同样提供 `/management-contexts`、`/clusters`、`/environments` 资源集合。
- 列表统一 `limit=50`（最大 200）、`offset`、`q`；返回 `items` 和 `total`。普通成员可读，修改限管理员。
- `GET /configs/{kind}/{owner_id}/draft` 返回 yaml_text、revision、validation、form_values。
- `PUT /configs/{kind}/{owner_id}/draft` 请求包含 base_revision、mode=yaml/form、yaml_text 或 field_updates；冲突返回 409，非法数据返回 422。
- `POST /configs/{kind}/{owner_id}/publish` 包含 base_revision，服务端重新校验后创建不可变版本；不调用 dingo。
- `GET /configs/{kind}/{owner_id}/versions` 和 `GET /configs/{kind}/{owner_id}/diff?from=1&to=2`；差异必须脱敏。

kind 只允许 environment/cluster。未知字段更新不得直接转化为 ORM 属性修改。资产归档与关系检查在同一事务完成。

### YAML 编辑语义

选择 ruamel.yaml 的 round-trip 模式，保留未知字段和注释；限制输入 1MiB，拒绝重复键、自定义标签、多文档和递归别名。第一版不允许 YAML alias/merge key，以免表单局部更新意外修改多个位置；导入时明确报错，不自动展开。

表单字段使用服务端白名单路径，不接受任意 JSONPath。数组或高级结构无法表达时维持 YAML 编辑。没有远端 dingo schema 时，原生拓扑版本标记“仅完成语法校验，尚未通过工具校验”；后续运维提交必须补做工具检查。

非法 YAML 保留在浏览器编辑器中，API 返回具体行列错误，不替换最后有效草稿。revision 冲突时提供“加载远端版本”和复制本地文本的操作，不能静默覆盖。

检测到疑似明文秘密时阻止发布并指出字段路径，不在错误响应中回显值。对 YAML、日志和配置差异统一使用脱敏策略；凭据引用不转换为明文返回网页。

### 登录和本地部署

本地账号是当前默认方案，后续保留统一身份系统适配点。密码用成熟密码哈希库，随机 session token 只保存摘要；浏览器使用 HttpOnly、SameSite cookie，部署时启用 Secure。写操作验证 CSRF token。管理员通过一次性命令交互创建，不能通过前端任意提升角色。

首次开发启动不自动发现主机、不访问测试集群。Compose 启动数据库、API 和网站，真实 Worker 要等后续阶段才启用。

## 后续阶段交付边界

1. **任务与测试闭环**：目录同步、勾选测试、参数预览、不可变快照、任务领取、资源锁、日志、取消、报告、重跑。先用本地 fixture 验证，再在用户指定环境接入真实执行。
2. **dingo 只读导入**：上下文序列化、工具版本及能力探测、集群目录/拓扑/实例采集、原始输出保留、解析失败状态。hosts/config/cluster 的版本差异用 fixture 测试。
3. **集群运维**：部署、启动、停止、重启、更新和分类清理；复用任务及资源锁，加入计划确认和事后检查。只有真正接入的操作才开放按钮。

每个阶段有单独实施计划。完成第一阶段不代表第一版全部验收通过。

## 调度和 Worker 约束

后续调度使用数据库事务领取任务和写入资源预留，资源键有唯一约束。锁按统一顺序获取；数据库连接释放的事务锁不能代替持续数小时的资源预留记录。

Worker 报告必须携带 attempt_id 和领取 token，过期 attempt 的结果拒绝覆盖新状态。心跳缺失保留资源预留并进入待检查，禁止仅因租约过期就再次派发会改变远端的任务。

集群、机器冲突域、管理上下文同时参与检查。人工操作也可能改变 dingo 当前集群，因此平台专用上下文与执行前目标校验都是必要前提。

## 资料依据

- [React TypeScript 支持](https://react.dev/learn/typescript)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [PostgreSQL 锁机制](https://www.postgresql.org/docs/current/explicit-locking.html)
- [ruamel.yaml round-trip 行为](https://yaml.dev/doc/ruamel.yaml/detail/)

这些资料用于核对技术能力；选型、阶段划分与数据模型是本项目的设计决定。
