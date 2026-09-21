# 第一阶段执行记录

执行分支：`feat/platform-foundation`。实现范围对应 2026-09-21 第一阶段计划，顺序执行，没有使用子代理，没有连接或操作真实 DingoFS 集群。

## 实现映射

| Task | 交付 |
| --- | --- |
| 1 基础 | FastAPI 工厂、PostgreSQL、Alembic、React/TypeScript、Compose、存活与就绪接口 |
| 2 登录 | Argon2 密码、会话摘要、HttpOnly cookie、CSRF、管理员 CLI、管理员/成员权限 |
| 3 资源 | 四类资源、搜索分页、关联与归档保护、并发修订校验、审计 |
| 4 配置 | YAML round trip、受限表单更新、输入限制、不可变版本与差异 |
| 5 网页 | 真实 API、错误与冲突保留本地编辑、远端草稿对照、复制与合并入口 |
| 6 验收 | 后端测试、前端测试、浏览器流程、Docker 构建、重启持久化、启动文档 |

## 实施裁定

- 初始仓库没有提交，直接创建特性分支，在独立 `/tmp` 构建目录编写和验证，再同步到用户指定新项目。没有复用或改动测试套件仓库。
- 按实际体量合并示例文件：登录 schema 放在 auth/routes.py；配置 schema/service/redaction 放在 configuration/routes.py 与 yaml_document.py；四类资源页面共用 InventoryPage，避免重复 CRUD 实现。后端测试统一于 test_platform.py。
- 数据库使用一份基础迁移和一份审计/成员关系元数据增量迁移，替代计划示例中的三份迁移。已在真实临时 PostgreSQL 上验证。
- `document_kind` 由 owner_kind 唯一推导，避免保存可矛盾的重复字段；API 返回明确文档类型。
- 关联表预留 role/managed；当前集群成员默认 unclassified / false，环境成员默认 client。未探测时不推断集群角色或接管权限；详细角色和接管策略跟随后续 dingo 导入。
- 资产/配置写事务共享短期 PostgreSQL advisory lock，保证跨表关联与归档、修订号校验的一致性。不能把它用于未来长任务资源预留。
- 审计仅存成功事务的操作者、动作、资源、字段名、结果和请求 ID。失败请求由 HTTP 错误与请求 ID 返回，失败审计、审计查询界面留在后续增强；不存原始配置差异或凭据值。
- 常用参数为 patch 表单，显示当前值作为提示，仅提交填写的字段。存在一种编辑模式的未保存修改时，另一种模式暂不可编辑，避免两份草稿相互覆盖。
- 来源校验在浏览器验证中发现开发代理 Host 被改写；修正 Vite 为 changeOrigin=false，保留后端来源校验。原生 select 添加明确 aria-label，修正真实浏览器标签定位问题。
- 代码审查由当前执行者逐文件完成，遵循已确认的不使用子代理要求。重点审查权限依赖、关系事务、秘密错误回显、配置版本不可变性、远端操作入口边界。

## TDD 记录

1. 后端第一批测试在缺少 app 模块时失败，实现后 16 passed。
2. 搜索分页与凭据模式测试失败（缺 total、rados.key 被接受），修复后 19 passed。
3. 配置元数据/错误定位测试失败（缺 document_kind），增加响应契约与安全行列错误；并发更新实测只允许一个成功。
4. 前端测试在缺 ConfigEditor 时失败；实现后验证 422/409 保留输入、只读权限和切换视图。
5. 冲突对照测试先因缺少“查看远端版本”失败，实现远端草稿对照后通过。

最终验证命令和结果见 PHASE1_ACCEPTANCE.md。
