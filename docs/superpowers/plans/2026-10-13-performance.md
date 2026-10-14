# Performance Implementation Plan

**Goal:** 网页创建单客户端 fio/elbencho 性能任务，跟踪日志与进度，统一查看报告。
**Architecture:** 独立 performance 模块；参数/命令、远端 supervisor、任务服务、页面分层。机器互斥，远端状态原子保存，API轮询并在重启后继续采集。
**Tech Stack:** FastAPI/SQLAlchemy/PostgreSQL、SSH/Python、React、现有dtt。
**Spec:** docs/superpowers/specs/2026-10-13-performance-design.md

## Global Constraints
自主实施，不使用子代理。保留现有修改。仅专属临时目录进行实际小规模验证。完成后构建部署。

## Review Focus
路径注入与已卸载目标；文件数量/总量冲突；进程结束但无有效报告；断连不重复启动；取消不影响其他容器。

- [x] 参数与命令：schemas.py、commands.py、test_performance.py；先验证约束失败再实现纯函数。
- [x] 远端执行：remote_runner.py、transport.py；验证顺序、失败、取消、报告、幂等启动。
- [x] 数据和API：models.py、routes.py、manager.py、迁移；验证权限、机器互斥、快照与报告读取。
- [x] 页面：PerformancePage.tsx和测试，导航与参数表单、轮询、日志、报告。
- [x] 验证与发布：相关测试、构建、隔离真实工具验证、迁移与部署、线上健康检查。

验收：参数/远端监督/API及工具部署相关测试通过；真实128机器fio和elbencho各16MiB、各2轮均通过，任务871cadc3-5b8c-4279-9c56-cb755fa0565c。兼容旧镜像入口：dtt部署附带只读性能运行时，dtt仓库18项CLI测试通过。
