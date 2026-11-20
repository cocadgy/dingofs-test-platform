import type { Tool } from "../performance/types";

export type GuidedPerformanceForm = {
  name: string; machineId: string; targetKind: "directory" | "mount"; targetPath: string;
  tools: Exclude<Tool, "mdtest">[]; duration: number; durationUnit: "seconds" | "minutes" | "hours";
  dataset: number; datasetUnit: "MiB" | "GiB" | "TiB"; rw: string;
  concurrency: number; blockSize: number; blockUnit: "KiB" | "MiB" | "GiB" | "TiB";
  rounds: number; direct: boolean; iodepth: number; readPercent: number;
  cleanupData: boolean; timeoutMinutes: number;
  mlperfModel: "resnet50" | "unet3d" | "cosmoflow";
  mlperfEpochs: number; mlperfAccelerators: number;
  mlperfScenario: 'training' | 'checkpointing' | 'kvcache';
  checkpointMode: 'write' | 'read' | 'write-read'; checkpointCount: number;
  checkpointModel: 'custom' | 'llama3-8b';
  kvModel: string; gpuMemoryGiB: number; cpuMemoryGiB: number;
};

const seconds = { seconds: 1, minutes: 60, hours: 3600 };
const bytes = { MiB: 1024 ** 2, GiB: 1024 ** 3, TiB: 1024 ** 4 };
const blockBytes = { KiB: 1024, ...bytes };
const integer = (value: number, min: number, max: number) => Number.isInteger(value) && value >= min && value <= max;
export const mlperfModels = {
  resnet50: { label: "ResNet50", bytesPerFile: 143439748, samplesPerFile: 1251, batchPerAccelerator: 400 },
  unet3d: { label: "UNet3D", bytesPerFile: 146600628, samplesPerFile: 1, batchPerAccelerator: 7 },
  cosmoflow: { label: "CosmoFlow", bytesPerFile: 2828486, samplesPerFile: 1, batchPerAccelerator: 1 },
} as const;

export const defaultGuidedPerformanceForm = (): GuidedPerformanceForm => ({
  name: `性能测试 ${new Date().toLocaleString()}`, machineId: "", targetKind: "directory", targetPath: "",
  tools: [], duration: 60, durationUnit: "seconds", dataset: 1, datasetUnit: "GiB", rw: "write",
  concurrency: 4, blockSize: 1, blockUnit: "MiB", rounds: 1, direct: true, iodepth: 1,
  readPercent: 50, cleanupData: false, timeoutMinutes: 0,
  mlperfModel: "resnet50", mlperfEpochs: 5, mlperfAccelerators: 1,
  mlperfScenario: 'training', checkpointMode: 'write-read', checkpointCount: 1, checkpointModel:'custom',
  kvModel: 'llama3.1-8b', gpuMemoryGiB: 0, cpuMemoryGiB: 0,
});

export function guidedPerformanceTotals(form: GuidedPerformanceForm) {
  const runtimeSeconds = form.duration * seconds[form.durationUnit];
  const datasetBytes = form.dataset * bytes[form.datasetUnit];
  const timedToolCount = form.tools.filter(tool => tool !== "mlperf").length;
  const measuredSeconds = runtimeSeconds * form.rounds * (timedToolCount + (form.tools.includes('mlperf') && form.mlperfScenario === 'kvcache' ? 1 : 0));
  const model = mlperfModels[form.mlperfModel] || mlperfModels.resnet50;
  const accelerators = integer(form.mlperfAccelerators, 1, 1024) ? form.mlperfAccelerators : 1;
  const rawFiles = Math.max(Math.ceil(datasetBytes / model.bytesPerFile), accelerators,
    Math.ceil(3 * model.batchPerAccelerator * accelerators / model.samplesPerFile),
    form.mlperfModel === "cosmoflow" ? 4 * accelerators : 0);
  const mlperfFileCount = Math.ceil(rawFiles / accelerators) * accelerators;
  const mlperfDatasetBytes = form.mlperfScenario === 'checkpointing' ? (form.checkpointModel === 'llama3-8b' ? 8030261248 * 14 : datasetBytes) * form.checkpointCount : form.mlperfScenario === 'kvcache' ? datasetBytes : mlperfFileCount * model.bytesPerFile;
  const combinedBytes = datasetBytes * timedToolCount + (form.tools.includes("mlperf") ? mlperfDatasetBytes : 0);
  const defaultTimeoutMinutes = Math.max(120, Math.ceil(measuredSeconds / 60) + 30);
  return { runtimeSeconds, datasetBytes, measuredSeconds, combinedBytes, defaultTimeoutMinutes, mlperfFileCount, mlperfDatasetBytes, timedToolCount };
}

export function validateGuidedPerformance(form: GuidedPerformanceForm): string {
  const totals = guidedPerformanceTotals(form);
  if (!form.machineId) return "请选择目标机器";
  if (!form.targetPath.startsWith("/") || form.targetPath === "/" || /(^|\/)\.\.(\/|$)|[\n\r\0:\[\],]/.test(form.targetPath) || /^\/(dev|proc|sys)(\/|$)/.test(form.targetPath)) return "请填写有效的绝对目标目录";
  if (!form.tools.length) return "请选择至少一种测试工具";
  if (!form.name.trim() || form.name.length > 120) return "请填写任务名称（最多 120 字）";
  if (!integer(form.concurrency, 1, 1024)) return "并发数需为 1 至 1024";
  if (!integer(totals.datasetBytes, 1, 1024 ** 5)) return "数据量需为有效大小";
  if (!integer(form.rounds, 1, 100)) return "轮数需为 1 至 100";
  if (form.tools.includes("mlperf")) {
    if (form.mlperfScenario === 'checkpointing') {
      if (!integer(form.checkpointCount, 1, 1000)) return '检查点次数需为 1 至 1000';
      if (form.checkpointModel === 'llama3-8b' && form.concurrency !== 8) return 'Llama3 8B 完整检查点请设置 8 个进程；小规模测试请选择自定义大小';
    } else if (form.mlperfScenario === 'kvcache') {
      if (!['tiny-1b','mistral-7b','llama2-7b','llama3.1-8b','llama3.1-70b-instruct'].includes(form.kvModel)) return '请选择支持的 KV Cache 模型';
      if (!integer(totals.runtimeSeconds, 1, 86400)) return 'KV Cache 测试时长需为 1 至 86400 秒';
      if ([form.cpuMemoryGiB, form.gpuMemoryGiB].some(v => !Number.isFinite(v) || v < 0 || v > 1048576)) return '缓存层内存需为有效的非负 GiB 数值';
    } else {
    if (!(form.mlperfModel in mlperfModels)) return "请选择支持的 MLPerf 模型";
    if (!integer(form.mlperfAccelerators, 1, 1024)) return "模拟加速器数量需为 1 至 1024";
    if (!integer(form.mlperfEpochs, 1, 1000)) return "每轮 epochs 需为 1 至 1000";
    }
    if (!integer(totals.mlperfDatasetBytes, 1, 1024 ** 5)) return "MLPerf 预计数据量超出支持范围";
  }
  if (totals.timedToolCount) {
    if (!integer(totals.runtimeSeconds, 1, 604800)) return "测量时长需为 1 至 604800 秒的整数";
    if (totals.datasetBytes % form.concurrency !== 0) return "数据量需有效且能被并发数整除";
    if (!integer(form.iodepth, 1, 1024)) return "I/O 深度需为 1 至 1024";
    const blockSizeBytes = form.blockSize * blockBytes[form.blockUnit];
    const fileBytes = totals.datasetBytes / form.concurrency;
    if (!integer(blockSizeBytes, 4096, fileBytes) || fileBytes % blockSizeBytes !== 0 || (form.direct && (blockSizeBytes % 4096 !== 0 || fileBytes % 4096 !== 0))) return "块大小需能整除单个文件大小并满足 Direct I/O 对齐要求";
    if (["rw", "randrw"].includes(form.rw) && !integer(form.readPercent, 0, 100)) return "混合读比例需为 0 至 100";
  }
  const timeout = form.timeoutMinutes || totals.defaultTimeoutMinutes;
  if (!integer(timeout, 1, 10000000) || timeout * 60 <= totals.measuredSeconds) return "任务总超时必须超过所有工具和轮次的测量时长";
  return "";
}

export function buildGuidedPerformancePayload(form: GuidedPerformanceForm) {
  const totals = guidedPerformanceTotals(form);
  return {
    name: form.name.trim(), machine_id: form.machineId, target_kind: form.targetKind,
    target_path: form.targetPath.trim(), cleanup_data: form.cleanupData,
    timeout_minutes: form.timeoutMinutes || totals.defaultTimeoutMinutes,
    tests: form.tools.map(tool => tool === 'mlperf' && form.mlperfScenario === 'checkpointing' ? {
      tool, mlperf_scenario: 'checkpointing', mlperf_model: form.checkpointModel, checkpoint_mode: form.checkpointMode,
      checkpoint_count: form.checkpointCount, checkpoint_size: form.checkpointModel === 'custom' ? String(totals.datasetBytes) : undefined,
      concurrency: form.concurrency, rounds: form.rounds,
    } : tool === 'mlperf' && form.mlperfScenario === 'kvcache' ? {
      tool, mlperf_scenario: 'kvcache', mlperf_model: form.kvModel, runtime_seconds: totals.runtimeSeconds,
      total_size: String(totals.datasetBytes), gpu_memory_gib: form.gpuMemoryGiB, cpu_memory_gib: form.cpuMemoryGiB,
      concurrency: form.concurrency, rounds: form.rounds,
    } : tool === "mlperf" ? { tool, mlperf_model: form.mlperfModel,
      mlperf_epochs: form.mlperfEpochs, mlperf_accelerators: form.mlperfAccelerators,
      concurrency: form.concurrency, total_size: String(totals.datasetBytes), rounds: form.rounds,
    } : { tool, runtime_seconds: totals.runtimeSeconds,
      total_size: String(totals.datasetBytes), rw: form.rw, concurrency: form.concurrency,
      block_size: String(form.blockSize * blockBytes[form.blockUnit]), rounds: form.rounds,
      direct: form.direct, iodepth: form.iodepth,
      read_percent: ["rw", "randrw"].includes(form.rw) ? form.readPercent : undefined,
    }),
  };
}
