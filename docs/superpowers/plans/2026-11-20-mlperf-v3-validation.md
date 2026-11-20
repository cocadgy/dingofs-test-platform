# MLPerf 3.0 实施与验证记录

日期：2026-11-20。仅修改两个隔离工作树；未提交、合并、推送或部署。

## 实施结果

- DTT 固定 MLPerf Storage `v3.0` / Python 包 `3.0.46`，源码 `ce28a9888076eba5a58fdd93d1c0258bf27b7aa2`。
- DLIO `3.0.4`，源码 `edaf4bb3d6343ef2fb6b9f6dbafa6102032ae8bf`；运行环境 Python 3.12。
- 引导式性能测试支持 Training、Checkpoint、KV Cache；平台参数、命令、预览、重跑、报告一并适配。
- Checkpoint 支持写、读、写读、次数、进程数、自定义总大小；只读先准备数据，准备耗时不计入读取指标。引导页另提供完整 Llama3 8B 模型，不将大模型静默缩小。
- KV Cache 支持模型、用户数、时长、存储层容量及 GPU/CPU 缓存层。容量不是累计实际写入量，不下载模型权重。
- 旧训练请求/报告继续支持。旧命令的已支持单机预设在新版镜像转到新版适配器；不支持的高级参数明确拒绝并提示迁移。
- 所有结果注明内部比较，不是官方 MLPerf 提交成绩。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| DTT 自身完整 tests 套件 | 300 passed、2 skipped、237 subtests passed |
| 原生结果/新适配器回归 | 35 passed，含真实样本重放与错误身份拒绝 |
| 后端完整套件 | 1274 passed、254 skipped、32 failed、2 errors |
| 前端完整套件 | 585 passed、7 failed |
| 引导页/新报告重点组件 | 20 passed |
| 浏览器引导流程 | 4 passed；本地页面、模拟 API，不是真实集群任务 |
| TypeScript / Vite 生产构建 | 通过；仍有现有大 bundle 提示 |
| Bash 语法 / git diff --check | 通过 |

后端失败及错误的测试集合，与未修改 `0042a668fdded9814771f66edddd6a692bf8e6ee` 基线逐项比较完全一致。前端 7 项失败也在同一基线复现，属于缓存组资源操作/响应校验等原有测试。不将这些结果表述为“全仓测试全部通过”。

原生验收使用正式 Dockerfile 的 `mlperf-builder` 产物，组装到现有完整运行时的独立验证镜像；不是完整生产镜像发布。数据目录为 1 GiB tmpfs，结果目录为独立 512 MiB tmpfs。没有对 126/129 发起负载。

1. CosmoFlow：4 文件、1 epoch、1 进程，通过。
2. Custom Checkpoint：总大小 16 MiB、1 次写读、1 进程，通过。
3. Custom Checkpoint：总大小 16 MiB、2 次只读、2 进程，独立准备阶段和测量阶段均通过；汇总大小正确显示 16 MiB。
4. KV Cache：tiny-1b、5 秒、256 MiB 存储层、1 用户，通过。
5. 旧 `run_model.sh cosmoflow` 入口：4 文件、5 epochs、1 进程，通过。

前四项真实报告均交给平台 `mlperf_summary` 解析并通过。最小原生样本保存在 DTT `tests/fixtures/mlperf_v3_native.json`，保留有效配置和指标，移除不参与契约验证的系统清单及原始数组。

## 审查修复

独立审查发现 3 个 Important、无 Critical。均先建立失败用例，再修复验证：

- Checkpoint 核对真实进程数、大小、并行配置、路径、次数及所有 rank；KV 原生 JSON 记录并核对有效配置。
- 恢复 Training 完整 epoch、起止时间、时长及指标序列检查。
- Custom Checkpoint 的每 rank 指标归一化为汇总大小和带宽，原始证据保留。

另修正上游对小型 custom checkpoint 按完整 Llama 估算空间的错误。保留容量检查，不跳过空间保护。补丁只作用于 custom 容量计算及 KV 配置证据导出；执行时验证容量补丁行为后才记录补丁身份。

## 边界与后续

- 尚未做远端集群或大模型容量测试；没有声称大模型性能验证完成。
- 生产生效需要后续构建/分发新版 DTT 并部署平台，本次未执行。
- 保留原有脏子模块、依赖链接及生成文件，不混入本次源码范围。
- 小项待改进：参数对比报告中部分通用列仍带训练命名，可后续按场景进一步精简；不影响执行参数或指标。

本地日志：`/tmp/mlperf-v3-dtt-final.log`、`/tmp/mlperf-v3-backend-final.log`、`/tmp/mlperf-v3-frontend-final.log`、`/tmp/mlperf-v3-browser-final.log`、`/tmp/mlperf-v3-native-final-reviewed.log`、`/tmp/mlperf-v3-legacy-native.log`。
