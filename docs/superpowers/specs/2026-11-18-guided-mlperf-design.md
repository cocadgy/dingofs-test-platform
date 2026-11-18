# 引导式性能测试：MLPerf Storage

用户要求在已有性能测试引导增加 MLPerf；沿用其授权自主决定、不询问、无空闲集群的约束。本次只实现及本地验证，不部署、推送、合并或启动远端任务。

## 方案

采用 DTT 已集成的 MLPerf Storage v2.0 / DLIO，新增机器可读的 `-t mlperf -s benchmark` 适配入口，保留现有 `-s resnet50|unet3d|cosmoflow|checkpointing|all` 行为。平台复用性能任务的预览、运行、租约、日志、取消、重跑、报告。

不选仅添加一个工具下拉项：旧 MLPerf 命令固定轮次、带交互 TTY、缺少统一报告，无法保证平台正确显示完成状态。不升级为 MLPerf v3：超出本次兼容接入范围且当前镜像固定 v2.0。不将任务 timeout 伪装为原生测量时长。

## 范围和界面

- 工具选择新增「MLPerf Storage（训练 I/O）」；可与 fio、elbencho 同时选择，按顺序运行。
- 支持 ResNet50、UNet3D、CosmoFlow。Checkpointing 暂保留 DTT 原入口，不套用训练数据量参数。
- MLPerf 专属参数：模型（默认 resnet50）、模拟 H100 加速器数量（默认 1，1..1024）、每轮训练 epochs（默认 5，1..1000）。共享轮数默认 1，1..100；共享并发表示数据生成进程数，1..1024。
- 用户填写数据量（MiB/GiB/TiB），按模型名义文件大小向上换算完整文件数；至少有足够样本供每个模拟加速器完成一个 batch。展示「预计数据量」，不是精确磁盘占用。
- 三种模型的 v2.0 H100 配置：(名义字节/文件，样本/文件，batch/加速器) 分别为 resnet50=(143439748,1251,400)，unet3d=(146600628,1,7)，cosmoflow=(2828486,1,1)。resnet 文件大小为 ceil(114660.07*1251)。格式元数据、压缩和样本尺寸分布会令实际占用不同。
- 以数据量生成文件数时：取 ceil(请求字节/名义文件字节)、加速器数、ceil(batch*加速器数/样本数) 三者最大值，再向上取加速器数的倍数。明确传入文件数则必须满足这个最小值及整除要求，不能静默调整。
- MLPerf 不接受 runtime_seconds。仅选 MLPerf 时不显示 fio 的测量时长、读写模式、块大小、Direct I/O、I/O 深度；显示 epochs/轮次与「任务总超时」。混合选择时明确测量时长仅适用于 fio/elbencho，MLPerf 时间取决于完整轮次。
- 说明模拟 GPU，不要求实体 GPU；自定义数据量与 epochs 属内部对比测试，不声称官方合规成绩。

## 跨组件契约

TestSpec / ParameterMatrix 新增 tool=`mlperf`、mlperf_model enum、mlperf_epochs strict int、mlperf_accelerators strict int。字段默认值以上为准；对非 MLPerf 不生成额外矩阵轴。MLPerf 轴仅 model/epochs/accelerators/concurrency/total_size/file_count/rounds。规范化 file_size 为名义文件字节、file_count 为推导值、total_size 为预计总字节；rw=read、direct=false、block_size=0、iodepth=1、read_percent=null。已有工具行为不变。

命令：`dtt -t mlperf -s benchmark -m TARGET -o OUTPUT --mlperf-model MODEL --mlperf-epochs E --mlperf-accelerators A --concurrency P --file-count N --rounds R`。该入口不需要交互式 TTY。`--dry-run` 只输出 JSON、不运行工具/容器/生成数据，顶层 `format=dtt-mlperf-v1`，`tool=mlperf`，以上规范化计划字段均在顶层。平台在正式运行前复用已跟踪的预检进程组，核验这个契约；旧 DTT 给升级错误，不启动负载。

适配器直接调用原生 `mlpstorage training datagen` 一次，再依次执行每轮 `training run --loops 1`，传入 data_folder、num_files_train、epochs、加速器数与固定 H100。内部测试使用 open/allow-invalid-params，不要求或声称提交合规。所有训练及数据生成路径必须位于本任务目录，不读取或删除其他任务的数据。每轮报告目录独立，不能用上一轮文件充数。

输出 `performance-mlperf-<unique>/summary.json` 和自包含 index.html，以及每轮原生 JSON 摘要附件。summary format=`dtt-mlperf-v1`，plan 为 dry-run 相同计划，status=passed|failed，rounds 列表包含 round/status/metrics/native_reports/error，statistics 含 complete/requested_rounds/successful_rounds/metrics。原生指标的字段及单位必须依据固定版本源代码，samples_per_second 必须为正且有限，accelerator_utilization_percent 为有限的 0..100；若原生结果没有可核验的时间则不生成 measurement_seconds。轮数、模型/epochs/加速器/数据参数必须与请求一致，缺失/重复/损坏结果应失败，不仅凭退出码成功。准备耗时与训练命令 wall time 可展示，但不冒充原生测量。

报告必须保留合规声明。平台只显示有效原生指标，不给 MLPerf 捏造 IOPS、块延迟或固定测量时长。总超时、取消和不确定停止沿用既有生命周期。

## 验证

TDD 覆盖命令、参数矩阵、单位/数据量换算、旧版探测、原生报告完整性、失败与取消、网页预览及重跑。使用本地伪外部 CLI 的严格契约测试，不把它称为真实 MLPerf 压测；不安装大型框架或启动集群。完整套件的既有非通过项如实记录，性能专项及前端构建必须通过。

官方来源：https://github.com/mlcommons/storage/tree/v2.0 ，configs/dlio/workload/{resnet50,unet3d,cosmoflow}_h100.yaml。原始指标契约核对固定 DLIO `mlperf_storage_v2.0` 源码。
