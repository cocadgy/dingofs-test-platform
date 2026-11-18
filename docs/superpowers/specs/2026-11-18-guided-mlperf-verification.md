# MLPerf 引导式性能测试验证（2026-11-18）

## 已实现

- 性能测试引导新增 MLPerf Storage v2.0 训练 I/O，可单选或与 fio/elbencho 一起顺序执行。
- 模型：ResNet50、UNet3D、CosmoFlow；可设置数据量及单位、模拟 H100 加速器数、每轮 epochs、测试轮数、数据生成并发和任务总超时。
- 数据量按完整模型文件向上取整，每个模拟加速器至少三个完整 batch，以满足固定 DLIO 原生吞吐率算法；页面显示预计占用，不承诺精确物理文件大小。UNet3D 单加速器至少21个文件（约2.87GiB），填写更小数据量时会明确显示增大的预计占用。MLPerf 不使用 fio 测量秒数，训练必须完成完整轮次；超时是任务终止上限。
- 复用平台预览、确认、日志、取消、重跑和报告；逐场景及汇总显示 samples/s、模拟加速器利用率。训练用时只读取原生 epoch 记录，不伪造 IOPS、块延迟或固定时长。
- DTT 新入口 `dtt -t mlperf -s benchmark`，保留旧模型/checkpointing 入口。执行前校验机器可读计划，旧 DTT 提示升级。原生报告缺失、模型/epochs/数据参数不符或未完整完成轮次都不能报告成功。
- 自动安装及离线工具包收录新适配脚本，并支持安装后的平铺运行目录；源代码目录不是必需条件。原生 epoch 耗时舍入为 `0.00` 时保留有效结果但不展示无法准确计量的用时。
- 自定义规模属于内部性能对比，不作为官方 MLPerf 合规成绩。

## 验证证据

| 范围 | 结果 |
| --- | --- |
| 后端性能专项（最终三批次修复后） | 168 通过，2 个既有依赖弃用警告 |
| 后端全量 | 1480 通过，30 失败、9 跳过、2 错误；失败名称与前次基线一致，见下述记录 |
| DTT 性能专项 | 115 通过，190 subtests 通过 |
| DTT 最终全量（`PYTHONPATH=.`，localhost 绕过代理） | 262 通过、2 跳过，228 subtests 通过；后续仅更新正向夹具到三批次，并复验适配器专项 |
| DTT 最终适配器专项 | 15 通过；覆盖零舍入 epoch、非法耗时、平铺安装预检、1/2/3 批次边界；shell 语法检查通过 |
| 平台工具包相关测试 | 21 通过、5 项既有可选环境跳过 |
| 前端新增初始专项 | 26 通过 |
| 前端汇总页修复专项 | 24 通过；覆盖引导、任务页汇总入口、对比图表 |
| 前端最终引导专项 | 15 通过；包括三批次下限与实际数据量提示 |
| 前端最终全量 | 580 通过、7 个与基线一致的失败 |
| 最终 TypeScript / Vite | 通过；Vite 保留既有大分包警告 |
| Chromium 引导 | MLPerf-only、混合工具两条模拟 API 流程，最终复验2/2通过；仅有既有 NO_COLOR/FORCE_COLOR 环境警告 |
| 本地跨仓库联调 | 真实平台执行器 + 真实 DTT 适配器 + 模拟原生 CLI：三模型、各两轮、原生摘要/元数据/epoch 附件、收集、仅清理任务数据、保留无关标记全部通过；退出码0但无报告正确失败 |
| 真实安装布局预检 | 平台 source_files 真实清单 → 传输平铺文件 → 真实 DTT 包装脚本 → MLPerf typed plan 通过；没有 scripts 子目录、没有容器运行环境、未创建数据/输出目录 |

后端及前端已有失败列表见 [先前性能引导验证](2026-11-17-guided-performance-testing-verification.md)。未将完整平台套件描述为全部通过。

DTT 首次根目录 `pytest -q` 因 `tests.test_smoke_cli` 导入路径无法收集。改为 `PYTHONPATH=. pytest -q tests` 后出现两个 localhost 报告服务等待失败；只对 localhost 设置 NO_PROXY 后两个专项通过，再跑完整套件 256 通过。补充短 epoch、安装布局和三批次下限回归后，最终全量 262 通过。未为代理问题修改产品代码。

独立最终审查发现固定 DLIO 原生算法以 `(steps - 2)` 计算吞吐量，原先一个 batch 的最小值不足。前端、后端和 DTT 已统一为每加速器三个完整 batch；使用该原生关系验证 1/2/3 批次结果及拒绝条件。唯一一轮限定复审通过，未发现修复引入新的阻断问题。两个非阻塞项保留在下方限制中。

最终代码提交：平台 `79f189a4f9976e723aba1535ee9e41206dc290ca`；DTT `ece1c41bfd60df8083a70444e5e263434ab41fb7`。文档另行提交。

本次没有真实 MLPerf 压测、集群 API 写入、镜像构建、部署、服务重启、推送或 main 合并。平台与 DTT 更改保留在既有功能分支；上线需更新平台并构建/安装带新适配器的 DTT。真实集群性能及容器内原生 MLPerf 启动仍待空闲环境验证。

## 复验入口

- 后端：`python3 /tmp/report-cache-tests-20261117.py -q tests/test_performance.py tests/test_performance_api.py tests/test_performance_directory.py tests/test_performance_dtt.py tests/test_performance_matrix.py tests/test_performance_mdtest.py tests/test_performance_mlperf.py tests/test_performance_runner.py tests/test_performance_runtime.py`（隔离本地测试库）。
- DTT：`NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost PYTHONPATH=. python3 -m pytest -q tests`。
- 浏览器：本地 Vite 127.0.0.1:55173，`playwright test tests/guided-performance.spec.ts`；测试拦截并模拟全部 API，拒绝其他域请求。
- 本地联调：`.venv/bin/python /tmp/guided-mlperf-local-smoke-20261118.py`，仅模拟原生 mlpstorage，非真实压测证据。
- 安装布局：`.venv/bin/python /tmp/mlperf-installed-plan-smoke-20261118.py`，真实清单及包装器的无副作用预检。

## 自主决定及代价

1. 沿用镜像固定的 v2.0 三种训练模型；checkpointing 留在 DTT 原入口。代价：其他 MLPerf 工作负载需要再扩展。
2. MLPerf 使用完整 epochs/轮次和总超时，不伪装为定时 fio 模式。代价：不能承诺固定测量秒数。
3. 后端、前端、DTT 按文件归属并行实现，以固定接口联调收敛。代价：仍需真实容器/集群验证发现模拟器不能覆盖的环境问题。
4. 最小数据量从一个 batch 调整为每加速器三个完整 batch。固定版本原生函数计算已验证1/2/3个 batch 的吞吐率分别为负/零/正；保留严格的原生指标验证。代价：小数据量请求可能向上增加，尤其 UNet3D 至少约2.87GiB/加速器。

## 非阻塞限制

- 原生适配器直接独立运行时，转发 SIGTERM 后等待不响应的子进程可能无界；平台引导使用已有有界容器停止逻辑，实际引导取消受该逻辑约束。
- 多模型或跨最小数据量的加速器对比，图表可能因衍生文件大小/数量不同拆分分组；指标仍展示正确，当前引导每个任务只选一种 MLPerf 模型。
- 现有报告传输有大小预算，极大原生日志不保证全部传回；远端保留原始报告目录。本次未改造日志传输。
