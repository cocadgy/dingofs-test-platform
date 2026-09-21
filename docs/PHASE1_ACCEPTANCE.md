# 第一阶段验收

范围：基础网站、资产和配置管理。验收全部使用本地隔离数据库与测试账号，未连接 DingoFS 集群，也没有触发已有测试工具。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 后端 pytest / Python 3.12 / PostgreSQL 16 | 21 passed |
| 前端 Vitest | 5 passed |
| TypeScript + Vite 正式构建 | 通过 |
| Playwright 真实前后端 | 2 passed，覆盖多步完整流程 |
| Docker / Python 3.12 / Node 22 / PostgreSQL 16 | 构建与启动通过 |
| Alembic upgrade/check | 迁移与模型一致 |
| API 与数据库重启 | 资源、草稿和已发布版本保留 |
| 数据库停止 | /health/ready 返回 503 |
| Python 未定义/未使用代码检查 | 通过 |

浏览器流程覆盖：管理员登录 → 登记机器 → 管理上下文 → 集群 → 环境 → 表单更新 → YAML 高级字段 → 发布两版 → 版本差异 → 非法 YAML 保留 → 双页面修订冲突保留 → 刷新后版本可见 → 关联资源归档拒绝。另一个流程验证普通成员只读，直接调用修改 API 返回 403；管理员缺 CSRF 也返回 403。

后端还覆盖会话过期、账号禁用、登出失效、伪造角色、端口范围、重复上下文、未知关联、两线程并发修订校验、敏感配置拒绝、YAML 注释保留、多文档/标签/别名/超限拒绝以及旧版配置不可变。

## 可复现命令

详细环境隔离和测试库说明见 [DEVELOPMENT.md](DEVELOPMENT.md)。主要检查命令：

```bash
PYTHONPATH=backend/src .venv/bin/pytest backend/tests -q
cd frontend
npm test -- --run
npm run build
npm run e2e
```

首次真实部署时应另行创建管理员和安全数据库密码；测试账号仅存在于被销毁的验收实例中。

## 限制与后续

- 未连接真实环境，不代表 dingo 工具、集群部署或已有测试用例已接入。
- 当前配置发布只在数据库中生成版本，工具校验固定为未完成。
- 页面版本列表显示最近 100 版；API 可按任意已存在的两个版本号比较。
- credential_ref 是引用标识，尚无秘密存储对接；任意业务文本中伪装的秘密不能自动识别。
- 管理上下文唯一性基于登记的机器 ID、用户、规范化目录；远端主机别名/符号链接归一化尚未接入。
- 未实现测试目录、任务、Worker、日志报告与真实运维，按技术设计进入后续阶段。
- 后端分别在 Python 3.13 开发环境及 Python 3.12 正式镜像验证。测试依赖有 httpx/Starlette 弃用提示；非 root 镜像内 pytest 缓存目录不可写，只影响缓存，所有测试通过。
