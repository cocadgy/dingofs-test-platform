import type { Tool } from "../performance/types";

export type GuidedPerformanceForm = {
  name: string; machineId: string; targetKind: "directory" | "mount"; targetPath: string;
  tools: Exclude<Tool, "mdtest">[]; duration: number; durationUnit: "seconds" | "minutes" | "hours";
  dataset: number; datasetUnit: "MiB" | "GiB" | "TiB"; rw: string;
  concurrency: number; blockSize: number; blockUnit: "KiB" | "MiB" | "GiB" | "TiB";
  rounds: number; direct: boolean; iodepth: number; readPercent: number;
  cleanupData: boolean; timeoutMinutes: number;
};

const seconds = { seconds: 1, minutes: 60, hours: 3600 };
const bytes = { MiB: 1024 ** 2, GiB: 1024 ** 3, TiB: 1024 ** 4 };
const blockBytes = { KiB: 1024, ...bytes };
const integer = (value: number, min: number, max: number) => Number.isInteger(value) && value >= min && value <= max;

export const defaultGuidedPerformanceForm = (): GuidedPerformanceForm => ({
  name: `性能测试 ${new Date().toLocaleString()}`, machineId: "", targetKind: "directory", targetPath: "",
  tools: [], duration: 60, durationUnit: "seconds", dataset: 1, datasetUnit: "GiB", rw: "write",
  concurrency: 4, blockSize: 1, blockUnit: "MiB", rounds: 1, direct: true, iodepth: 1,
  readPercent: 50, cleanupData: false, timeoutMinutes: 0,
});

export function guidedPerformanceTotals(form: GuidedPerformanceForm) {
  const runtimeSeconds = form.duration * seconds[form.durationUnit];
  const datasetBytes = form.dataset * bytes[form.datasetUnit];
  const measuredSeconds = runtimeSeconds * form.rounds * form.tools.length;
  const combinedBytes = datasetBytes * form.tools.length;
  const defaultTimeoutMinutes = Math.max(120, Math.ceil(measuredSeconds / 60) + 30);
  return { runtimeSeconds, datasetBytes, measuredSeconds, combinedBytes, defaultTimeoutMinutes };
}

export function validateGuidedPerformance(form: GuidedPerformanceForm): string {
  const totals = guidedPerformanceTotals(form);
  if (!form.machineId) return "请选择目标机器";
  if (!form.targetPath.startsWith("/") || form.targetPath === "/" || /(^|\/)\.\.(\/|$)|[\n\r\0:\[\],]/.test(form.targetPath) || /^\/(dev|proc|sys)(\/|$)/.test(form.targetPath)) return "请填写有效的绝对目标目录";
  if (!form.tools.length) return "请选择至少一种测试工具";
  if (!form.name.trim() || form.name.length > 120) return "请填写任务名称（最多 120 字）";
  if (!integer(totals.runtimeSeconds, 1, 604800)) return "测量时长需为 1 至 604800 秒的整数";
  if (!integer(form.concurrency, 1, 1024)) return "并发数需为 1 至 1024";
  if (!integer(totals.datasetBytes, 1, 1024 ** 5) || totals.datasetBytes % form.concurrency !== 0) return "数据量需有效且能被并发数整除";
  if (!integer(form.rounds, 1, 100)) return "轮数需为 1 至 100";
  if (!integer(form.iodepth, 1, 1024)) return "I/O 深度需为 1 至 1024";
  const blockSizeBytes = form.blockSize * blockBytes[form.blockUnit];
  const fileBytes = totals.datasetBytes / form.concurrency;
  if (!integer(blockSizeBytes, 4096, fileBytes) || fileBytes % blockSizeBytes !== 0 || (form.direct && (blockSizeBytes % 4096 !== 0 || fileBytes % 4096 !== 0))) return "块大小需能整除单个文件大小并满足 Direct I/O 对齐要求";
  if (["rw", "randrw"].includes(form.rw) && !integer(form.readPercent, 0, 100)) return "混合读比例需为 0 至 100";
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
    tests: form.tools.map(tool => ({ tool, runtime_seconds: totals.runtimeSeconds,
      total_size: String(totals.datasetBytes), rw: form.rw, concurrency: form.concurrency,
      block_size: String(form.blockSize * blockBytes[form.blockUnit]), rounds: form.rounds,
      direct: form.direct, iodepth: form.iodepth,
      read_percent: ["rw", "randrw"].includes(form.rw) ? form.readPercent : undefined,
    })),
  };
}
