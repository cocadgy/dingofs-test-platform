# Guided Mount Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 实现与缓存组一致的多机、多客户端挂载引导。

**Architecture:** 独立引导页复用机器选择、TAG、模板、RDMA 和 ResourceOperationView。后端扩展现有资源计划及执行器，先生成不可变检查计划，再执行和核验失败项重试。

**Tech Stack:** React、TypeScript、FastAPI、SQLAlchemy、现有 SSH 执行服务。

**Spec:** docs/superpowers/specs/2026-11-05-guided-mount-design.md

## Global Constraints

- 一次一个文件系统；保留原 mount.create 请求兼容。
- 不自动卸载、覆盖已有挂载，不静默回退程序来源。
- 不保存认证密码；每个操作保留机器、IP、执行用户、命令证据。
- 工作区无关修改不得进入发布镜像。共享环境不执行真实挂载回归。

## Review Focus

- 下载错误或 TAG 变化：固定 digest，失败明确显示，禁止回退。
- 部分成功后断网：成功项不得重跑，未知项先核验。
- 机器配置差异：不得复制身份、冲突路径或错误 RDMA 设备。
- 草稿与任务恢复：用户切换、开始新任务不得恢复他人或旧完成任务。
- 检查与执行之间的变化：权限、机器版本、路径和端口必须重新核验。

## Task 1：多机计划与目录展开

Files: resources/schemas.py、service.py、bulk_create.py；新增 resources/mount_planning.py、tests/test_mount_planning.py。

接口：mount.plan 接收 fs_name、clients（每项包含 machine_id、target_user、count、mount_path、mount_options、程序来源）；输出普通 ResourceOperation。mount.create 支持 plan_id、retry_operation_id，仍接受旧字段。

- [ ] 编写失败测试：两台机器各 2 个客户端展开为 4 个唯一目标；同机重复路径拒绝；不同机器同路径允许；原单机请求保持兼容。
- [ ] 实现服务端展开、权限校验和不可变计划存储，沿用现有操作 revision、请求 ID 和认证挑战。
- [ ] 测试计划过期、机器变更、伪造重试目标与重复请求；运行相关 pytest。

## Task 2：程序准备、检查、执行和重试

Files: resources/commands.py、remote_helper.py、execution.py、mount_planning.py；新增 resources/mount_binary.py 与 tests/test_mount_binary.py、test_mount_plan_execution.py。

接口：prepare_mount_binary 接收默认/TAG/路径来源，返回校验后的客户端路径与版本；检查计划生成逐客户端执行目标；重试由服务端原操作结果决定。

- [ ] 编写失败测试覆盖 TAG digest 校验、缺失 dingo-client、已有目录权限、已挂载路径、端口冲突。
- [ ] 复用缓存二进制准备机制可复用部分，明确区分 dingo-client 和 dingo-cache；构造结构化命令而非拼接用户 shell。
- [ ] 实现先检查后执行；单个客户端保存结果。失败重试先核验原目标，成功项跳过，未知状态返回待核验。
- [ ] 用模拟远端测试部分失败、断网和幂等请求，不在共享客户端执行挂载。

## Task 3：引导模型与每机参数卡

Files: 新增 getting-started/guidedMountModel.ts、MountMachineCard.tsx 及对应测试；复用已有 TAG、RDMA、参数模板组件。

接口：MountDraft 保存 clusterId、fsName、source、tag、digest、rows；buildMountClients(draft) 输出 Task 1 的 clients；cloneMountSettings 只复制通用参数。

- [ ] 测试默认单客户端、子目录 /、多客户端路径预览与服务端一致、模板切换、机器继承不复制身份和目录、RDMA 不匹配清空。
- [ ] 实现常用/高级参数、模板加载保存、缓存组实时选择、逐机程序目录。
- [ ] 运行模型和组件 Vitest，核对显示参数等于实际提交参数。

## Task 4：四步流程与子引导返回

Files: 新增 GuidedMountFlow.tsx、GuidedMountFlow.test.tsx；修改 GettingStartedPage.tsx、App.tsx、getting-started.css，必要时为已有文件系统引导增加创建成功回调。

- [ ] 先测试 /start/mount 入口、步骤必填校验、DELETE 过滤、离开确认、新任务清理、按用户隔离的草稿恢复。
- [ ] 实现添加机器、添加集群、创建文件系统子流程，保留当前草稿并选中新资源；不新开标签。
- [ ] 接入 mount.plan → mount.create，复用认证挑战与 ResourceOperationView；展示每台机器结果及失败项重试。
- [ ] 测试重复点击、页面刷新、丢失响应、失败提示和部分成功，确保不会重复创建。

## Task 5：集成验证与部署

- [ ] 检查设计逐项覆盖，执行相关后端与前端测试、类型检查和生产构建。
- [ ] 复查权限、计划不可变性、目标路径和重试身份；检查差异中无凭据与无关改动。
- [ ] 从已提交功能补丁生成隔离发布快照，确认无活跃任务后部署，保留镜像回滚标签。
- [ ] 验证服务健康、入口页面与静态资源，提供提交号与手动验证步骤，不自动创建真实客户端。
