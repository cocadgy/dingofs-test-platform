# Existing Mount Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在挂载点页扫描多台机器的已有 DingoFS 挂载并只读展示归属。

**Architecture:** 增加非变更型资源动作 `mount.scan`，复用任务、权限、SSH 与认证机制；独立扫描模块从 proc 元数据构建白名单结果。独立前端扫描组件展示结果，不写入 ManagedResource。

**Tech Stack:** Python/FastAPI/SQLAlchemy、已有 SSH transport、React/TypeScript/Vitest。

**Spec:** `docs/superpowers/specs/2026-11-03-existing-mount-scan-design.md`

## Global Constraints

- 只扫描和展示，不纳管、不卸载、不重挂载。
- 不读取挂载内容，不修改现有客户端；不输出完整 argv 或凭据。
- 保留所有无关未提交修改；构建仅包含本任务及已提交代码。
- 扫描各步骤展示机器名、IP、扫描执行用户；客户端用户单独展示。

## Review Focus

- 无权限或 /proc 不可读：报告失败/无法确认，不伪装成功空结果。
- 同名文件系统不同集群：基于 MDS 端点集合核对。
- 机器/集群切换与异步响应：旧结果不得落到新集群。
- 多机器中一台失败：保留其余结果和每台机器错误。
- 容器 namespace/大量进程：说明可见性限制，限制耗时与结果大小。

### Task 1: 只读扫描及后端任务

**Files:** 新增 `backend/src/dingofs_platform/resources/mount_scan.py`、`backend/tests/test_mount_scan.py`、`backend/tests/test_mount_scan_api.py`；修改 resources 下 `schemas.py`、`commands.py`、`service.py`、`execution.py`、`remote_helper.py`。

**Interfaces:** `mount.scan` 参数 `machine_ids: list[str]`；每机器一步，扫描以 root 读取进程元数据，走现有 sudo 认证。结果 `data.mounts` 每行字段为 mount_id、mount_path、fs_name、pid、client_user、mds_addresses、cluster_match、reason、saved_resource_id（可空）。机器身份使用既有 step 字段。

- [ ] 先写失败测试：proc 转义路径、两种 flag 形式、mds URI、匹配/不匹配/缺失和多进程歧义；扫描不得调用生命周期动作。
- [ ] 实现独立扫描函数与远程脚本打包；严格参数验证，最多 20 台去重机器；当前 namespace 的 proc 读取和结果大小限制。
- [ ] 加入资源动作及 prepare 分支；每台独立执行，不生成 ManagedResource；错误保留在对应步骤并继续下一台。
- [ ] API 测试验证机器/集群权限、SSH 配置缺失、部分失败与 ManagedResource 数量不变；运行专项和后端回归。

### Task 2: 挂载页扫描入口及结果

**Files:** 新增 `frontend/src/features/resources/MountScan.tsx`、`MountScan.test.tsx`；最小修改 `ClusterResources.tsx`、`types.ts`，必要时新增独立样式文件。

**Interfaces:** 复用 `execute` 提交 `mount.scan`，接收 ResourceOperation 步骤结果；从 snapshot.machines 选择目标，过滤不可管理机器。动作保持在挂载页，扫描结果不加入已保存挂载操作选择项。

- [ ] 先写失败测试：机器多选提交、按钮禁用、成功/空/部分失败、机器与客户端用户展示、旧结果不跨集群显示。
- [ ] 实现独立组件，展示当前集群/其他集群/无法确认、已保存标记和扫描时间，说明仅扫描当前命名空间。
- [ ] 运行前端测试与构建；对已有失败与基线逐项比较。

### Task 3: 只读验收与部署

- [ ] 复核扫描没有写操作且无关工作区修改未入提交。
- [ ] 对 129 做一次只读扫描，核对已观察到的挂载与 MDS 地址；不做纳管或卸载。
- [ ] 提交本任务代码、构建隔离镜像；确认没有活动任务后部署并检查健康状态。

**执行建议：** 当前会话顺序实施，后端完成后接入前端；结束时一次独立复查。
