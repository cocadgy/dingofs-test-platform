# 保留残留后隔离重跑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许管理员核验已结束任务后保留残留、释放占用，再部署新版并隔离重跑。
**Architecture:** 新增显式释放服务与接口；复用远端快照和结束证明，不削弱现有自动释放条件。释放记录保存在任务结果中，残留账本与失败结果保留。旧残留清理另行申请原范围的互斥占用。
**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL、React/TypeScript。
**Spec:** `docs/superpowers/specs/2026-11-13-retained-run-release-design.md`

## Global Constraints

- 仅管理员明确确认后操作；身份或恢复状态不明时拒绝。
- 不清理旧资源，不把 retained/unknown 改为 removed，不伪造成功结果。
- 不影响其他任务的锁；禁止与新任务并发清理旧资源。
- 新任务重新预检，使用独立任务 ID、文件系统名称及目录。

## Review Focus

- 远端结束证明与持久化启动身份不一致：拒绝释放。
- 读取远端过程中新增清理或状态变化：在相同锁顺序下重核验。
- 重复请求发生在新任务已取得锁之后：不得释放新任务的锁。
- 旧残留清理遇到新任务占用：拒绝执行，不能沿用释放前的授权。
- 安装新版后旧任务仍需核验：必须使用原不可变运行环境，不能使用 current 链接。

### Task 1: 管理员核验释放与后续清理互斥

**Files:**
- Create: `backend/src/dingofs_platform/functional/retention_release.py`
- Modify: `backend/src/dingofs_platform/functional/routes.py`
- Modify: `backend/src/dingofs_platform/functional/retention_cleanup.py`
- Modify: `backend/src/dingofs_platform/operations/leases.py`
- Test: `backend/tests/test_functional_retention_release.py`
- Test: `backend/tests/test_functional_retention_cleanup.py`（若现有命名不同，沿用现有清理测试文件）

**Interfaces:** `release_retained_run(db, actor, run_id, *, confirmed)` 返回 released、released_keys、retained_count；接口 `POST /functional/runs/{id}/resources/release-retained`。复用 `Transport.poll_child` 和服务端冻结的子任务请求；不接受浏览器提供的远端证据。

- [ ] 写失败测试：管理员成功释放但账本不变；普通用户/未确认/活动任务/远端失败/结束身份不一致/恢复失败/清理中均拒绝；重复调用不影响另一 owner 的锁。
- [ ] 运行新增测试，确认因缺少服务失败。
- [ ] 实现事务化核验、显式释放及审计，保留普通 `release_verified` 原有条件。
- [ ] 写失败测试并实现释放后旧残留清理重新获取互斥占用；冲突或重新核验失败时不发送清理命令。
- [ ] 运行新增测试及现有 retention、cleanup、lease 测试；运行后端工程测试并记录任何已有失败。
- [ ] 提交后端实现及测试。

### Task 2: 明确确认与残留状态展示

**Files:**
- Modify: `frontend/src/features/functional/FunctionalPage.tsx`
- Modify: `frontend/src/features/functional/RunDetail.tsx`
- Modify: `frontend/src/features/functional/FunctionalRetention.test.tsx`
- Modify: 现有功能任务类型定义（按现有 Run 类型来源定位）。

**Interfaces:** 使用 Task 1 接口；仅管理员显示“保留残留并释放占用”，确认说明不执行清理。

- [ ] 写失败测试：取消确认不请求；确认后请求一次；处理中禁用；失败不显示成功；完成后显示“残留已保留、占用已释放”。
- [ ] 实现按钮、确认提示、结果刷新；不将旧失败任务改为成功。
- [ ] 运行前端相关测试、类型检查和构建，提交。

### Task 3: 审查、部署和网页复测

- [ ] 独立审查权限、锁顺序、身份重核验、幂等性与旧残留清理路径；重要问题以失败测试修复。
- [ ] 构建并部署平台，保留旧运行环境与源代码归档，检查健康状态。
- [ ] 网页确认释放指定旧任务占用，确认残留账本数量及身份未被修改。
- [ ] 安装已构建的 shared-mount 修复镜像，更新对应框架源版本，核验镜像与运行能力。
- [ ] 从网页重新预检并运行原 trash/config/TC-CONFIG-001.yaml；记录任务链接、最终状态、清理与报告结果，不重复提交。
- [ ] 推送已获授权仓库的提交；平台仓库推送前确认目标也已获授权。汇报实际完成与未完成项。
