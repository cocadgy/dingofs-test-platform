# MLPerf 短测修复验收（2026-11-18）

## 修复与部署

- 平台代码：`ca99cab`。CosmoFlow 前后端最小文件数一致；Nginx 为 plain/scene MLPerf 报告保留同源嵌入策略。
- DTT 代码：`317d60a`（含 `3464de0`）。仅允许四个已知可选 checkpoint 汇总字段为 NaN；必需指标仍严格校验，原生报告逐字节保留。
- CosmoFlow 每个模拟加速器至少四个文件，同时保留三个完整 batch 和文件数整除约束。ResNet50/UNet3D 下限不变。
- API/Web 镜像均为 `mlperf-fix-ca99cab`，发布入口：`/mnt/disk5/daigy/dingofs-platform-releases/20261118-mlperf-fix/compose.sh`。
- 性能 DTT：`/home/jenkins/.local/share/dingofs-platform/tools/dtt-performance/current` → `317d60a-20261118`。适配器 SHA-256：`ad4367c8e7a99dba6aaae21bfac118fbf1ad57687877e2284f8bcbfa7b24fd79`。
- 功能测试 DTT 保持 `tools/dtt/e9bc43ad1337908f-image-umslzc9d`。只替换 API/Web，无数据库迁移，没有合并或推送 main。旧镜像和 `ece1c41-20261118` 性能工具目录均保留，可在无活动任务时切回。

## 网页实际验收

使用 Chrome/Playwright 从“开始 → 性能测试”逐步选择并提交，未直接调用创建任务 API。目标为 dingo126（172.30.14.126），执行用户 jenkins；复用专用挂载 `/mnt/disk5/dingo_autotest/platform-fio-guide-20261118-30s`。

三个任务均请求 1 MiB、1 个模拟 H100、1 个数据生成进程、1 epoch、1 轮，并选择全部成功后清理数据。界面明确显示按模型补足后的数据量。

| 模型 | 实际计划 | 结果 | samples/s | 任务 |
| --- | --- | --- | --- | --- |
| ResNet50 | 1 文件，136.79 MiB | 通过 | 890.7142 | [7624efeb](http://172.30.14.126:58080/#/performance/7624efeb-9af7-4ee0-ad23-6cf39c6d1fcf) |
| UNet3D | 21 文件，2.87 GiB | 通过 | 10.7605 | [09b7da4d](http://172.30.14.126:58080/#/performance/09b7da4d-bb3a-4d59-a85e-2d0d50585002) |
| CosmoFlow | 4 文件，10.79 MiB | 通过 | 168.1050 | [1b74fede](http://172.30.14.126:58080/#/performance/1b74fede-da9a-4cb0-a68b-3d83de7564d2) |

- 三份实际 `reports/scene-001-mlperf/index.html` iframe 都成功加载，正文均为 `passed`，不再是 Chrome 拒绝加载页面。记录到的报告响应为 HTTP 200、HTML、单一 `frame-ancestors 'self'`，无 DENY。浏览器 pageerror 为空。
- 三份原生 epoch 文件都只有 epoch `1`，指标来自真实 native summary，不是模拟测试结果。原生 summary 与平台附件逐字节一致。
- UNet3D 原生 summary 仍包含四个 checkpoint NaN，训练关键指标有效且任务通过；没有修改原始数据来制造成功。
- 三个本次 `platform-performance-<ID>` 数据目录均已自动清理，报告保留。未清理此前失败任务的数据、现有挂载或其他文件系统。
- 此为模拟 H100 的短时内部兼容性验收，不是官方 MLPerf 合规结果或稳定性能结论。
- 截图证据：`/tmp/mlperf-fix-resnet50-report-20261118.png`、`/tmp/mlperf-fix-unet3d-report-20261118.png`、`/tmp/mlperf-fix-cosmoflow-report-20261118.png`。iframe 内容另经浏览器直接读取验证。

## 自动化验证

| 验证范围 | 结果 |
| --- | --- |
| DTT 全量（3464de0） | 264 通过、2 跳过、235 subtests 通过 |
| DTT 最终模型下限修正（317d60a） | 专项 18 通过、42 subtests 通过；新增 ResNet50 一/两加速器 RED → GREEN；未重复全量 |
| MLPerf 后端专项 | 44 通过，2 项既有依赖弃用警告 |
| 性能后端全部九个模块 | 174 通过，2 项依赖警告，28.86 秒 |
| 前端专项 | 15 通过 |
| 真实 Nginx 上游代理测试 | 4 通过，覆盖 MLPerf plain/scene、fio/elbencho 与通用 API 策略 |
| 前端构建和 API/Web 镜像 | 通过；既有大 chunk 警告保留 |
| 完整前端 | 580 通过、7 失败，与已有记录的七个失败名称一致 |
| 完整后端 | 1504 通过、9 跳过、31 失败、2 teardown 错误、24 警告，886.18 秒 |

后端失败/错误名称与修复前 `/tmp/fio-isolated-dtt-backend-verification-20261118.md` 逐项集合比较无差异；不能据此宣称整个项目全部通过，也没有扩展本次修复去处理这些旧失败。前端首次并行运行有额外 MountLogPage 超时，单独重跑后未复现。

原始日志：`/tmp/mlperf-live-fixes-backend-full-20261118.log`、`/tmp/mlperf-fix-performance-backend-20261118.log`、`/tmp/mlperf-platform-frontend-full-20261118.json`。TDD 日志和独立复审账本位于 `.superpowers/sdd/2026-11-18-mlperf-live-fixes/`。

## 证据保留与复审

- 独立 DTT 复审发现新四文件下限误及 ResNet50，已在 317d60a 修复并通过限定复审。平台独立复审和最终跨组件复审无阻塞项。
- 代理测试使用 report.html 而实际页面使用 index.html 的非阻塞覆盖差异，已通过上述三个真实 index.html iframe 验证补足。
- 旧 UNet3D 失败任务 `8fb1d9bb-1206-4d8e-abd0-08e9e4c2c08e` 的 state.json SHA-256 前后均为 `cc88a4648243c65bde4b1f081eab76ab3e12e162e85f83a0a2bfaf5787d61c0b`。
- 旧 CosmoFlow 失败任务 `d16f434e-3602-4356-816e-c6bdfa2a2974` 的 state.json SHA-256 前后均为 `bfd513a3c37bda3eddd12cc785f81d4b5b56e8deb776eb73d0a883b221aec143`。
- 最终 API healthy、Web running；平台任务、操作、会话、租约活动计数均为零。

## 执行裁定

1. 两仓库无交叉编辑的实现并行推进；潜在风险是参数规则不一致，已由跨组件复审及网页计划验收检查。
2. 既有全量失败不扩展到本次修复；代价是整个项目测试仍非全绿，已保留准确失败记录。
3. NaN 兼容只限四个可选 checkpoint 统计，未放宽关键指标；代价是其他未知异常仍会明确失败，不被伪装成成功。
