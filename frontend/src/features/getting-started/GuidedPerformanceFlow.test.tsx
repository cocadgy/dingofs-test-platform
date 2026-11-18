import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GuidedPerformanceFlow } from "./GuidedPerformanceFlow";
import { buildGuidedPerformancePayload, guidedPerformanceTotals, validateGuidedPerformance } from "./guidedPerformanceModel";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const options = { machines: [
  { id: "m1", name: "主机一", address: "192.0.2.1", ssh_user: "alice", maintenance: false },
  { id: "m2", name: "主机二", address: "192.0.2.2", ssh_user: "bob", maintenance: false },
], mounts: [
  { id: "v1", name: "文件系统一", state: "mounted", machine_id: "m1", path: "/mnt/one" },
] };
const base = { name: "性能测试", machineId: "m1", targetKind: "directory" as const, targetPath: "/data",
  tools: ["fio" as const], duration: 60, durationUnit: "seconds" as const,
  dataset: 1, datasetUnit: "GiB" as const, rw: "write", concurrency: 4,
  blockSize: 1, blockUnit: "MiB" as const, rounds: 1, direct: true,
  iodepth: 1, readPercent: 50, cleanupData: false, timeoutMinutes: 0,
  mlperfModel: "resnet50" as const, mlperfEpochs: 5, mlperfAccelerators: 1 };

test("normalizes duration and dataset once for every selected tool", () => {
  const payload = buildGuidedPerformancePayload({ ...base, tools: ["fio", "elbencho"], duration: 2,
    durationUnit: "minutes", dataset: 2, datasetUnit: "GiB" });
  expect(payload.tests).toEqual(["fio", "elbencho"].map(tool => ({ tool, runtime_seconds: 120,
    total_size: "2147483648", rw: "write", concurrency: 4, block_size: "1048576",
    rounds: 1, direct: true, iodepth: 1, read_percent: undefined })));
  expect(payload.timeout_minutes).toBeGreaterThan(4);
});

test("supports a 4 KiB block with a GiB dataset", () => {
  const payload = buildGuidedPerformancePayload({ ...base, blockSize: 4, blockUnit: "KiB" });
  expect(payload.tests[0].block_size).toBe("4096");
  expect(validateGuidedPerformance({ ...base, blockSize: 4, blockUnit: "KiB" })).toBe("");
});

test("MLPerf rounds nominal dataset to enough whole files per accelerator", () => {
  const form = { ...base, tools: ["mlperf"], dataset: 1, datasetUnit: "MiB",
    mlperfModel: "cosmoflow", mlperfEpochs: 5, mlperfAccelerators: 3 } as any;
  const totals = guidedPerformanceTotals(form);
  expect(totals.mlperfFileCount).toBe(3);
  expect(totals.combinedBytes).toBe(8485458);
  expect(totals.measuredSeconds).toBe(0);
  expect(buildGuidedPerformancePayload(form).tests).toEqual([{ tool: "mlperf", mlperf_model: "cosmoflow",
    mlperf_epochs: 5, mlperf_accelerators: 3, concurrency: 4, total_size: "1048576", rounds: 1 }]);
});

test("MLPerf-only ignores invalid fio controls but validates training controls", () => {
  const form = { ...base, tools: ["mlperf"], duration: 0, rw: "invalid", blockSize: 0,
    direct: true, iodepth: 0, mlperfModel: "resnet50", mlperfEpochs: 5, mlperfAccelerators: 1 } as any;
  expect(validateGuidedPerformance(form)).toBe("");
  expect(validateGuidedPerformance({ ...form, mlperfEpochs: 0 })).toMatch(/epochs/);
  expect(validateGuidedPerformance({ ...form, mlperfAccelerators: 0 })).toMatch(/加速器/);
  expect(validateGuidedPerformance({ ...form, mlperfModel: "checkpointing" })).toMatch(/模型/);
});

test("mixed payload retains timed runtime only on fio and elbencho", () => {
  const form = { ...base, tools: ["fio", "mlperf", "elbencho"], mlperfModel: "resnet50",
    mlperfEpochs: 7, mlperfAccelerators: 2 } as any;
  const payload = buildGuidedPerformancePayload(form);
  expect(payload.tests.map((item: any) => item.tool)).toEqual(["fio", "mlperf", "elbencho"]);
  expect(payload.tests[1]).toEqual({ tool: "mlperf", mlperf_model: "resnet50", mlperf_epochs: 7,
    mlperf_accelerators: 2, concurrency: 4, total_size: "1073741824", rounds: 1 });
  expect(payload.tests[0]).toHaveProperty("runtime_seconds", 60);
  expect(payload.tests[2]).toHaveProperty("runtime_seconds", 60);
  expect(guidedPerformanceTotals(form).measuredSeconds).toBe(120);
});

test("MLPerf-only shows training settings and omits fio controls", async () => {
  vi.mocked(api).mockResolvedValue(options);
  render(<GuidedPerformanceFlow onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/data" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByLabelText("MLPerf Storage"));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByLabelText("训练模型")).toHaveValue("resnet50");
  expect(screen.getByLabelText("模拟 H100 加速器数量")).toHaveValue(1);
  expect(screen.getByLabelText("每轮训练 epochs")).toHaveValue(5);
  expect(screen.queryByLabelText("测量时长")).toBeNull();
  expect(screen.queryByLabelText("读写模式")).toBeNull();
  expect(screen.queryByLabelText("块大小")).toBeNull();
  expect(screen.queryByLabelText("Direct I/O")).toBeNull();
  expect(screen.getByText(/内部对比测试/)).toBeTruthy();
  expect(screen.getByText(/预计数据量/)).toBeTruthy();
});

test("MLPerf preview becomes stale after training edit and submits only once", async () => {
  let resolveRun!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async path => path === "/performance/options" ? options :
    path === "/performance/preview" ? { total_bytes: 1147517984, tests: [{ tool: "mlperf", command: "dtt -t mlperf", parameters: {} }] } :
    path === "/performance/runs" ? new Promise(resolve => { resolveRun = resolve; }) : []);
  const navigate = vi.fn();
  render(<GuidedPerformanceFlow onNavigate={navigate} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/data" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByLabelText("MLPerf Storage"));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
  await screen.findByText("dtt -t mlperf");
  fireEvent.click(screen.getByRole("button", { name: "上一步" }));
  fireEvent.change(screen.getByLabelText("每轮训练 epochs"), { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("button", { name: "开始测试" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
  await screen.findByText("dtt -t mlperf");
  fireEvent.click(screen.getByRole("button", { name: "开始测试" }));
  fireEvent.click(screen.getByRole("button", { name: "开始测试" }));
  expect(vi.mocked(api).mock.calls.filter(call => call[0] === "/performance/runs")).toHaveLength(1);
  resolveRun({ id: "mlperf-run" });
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("#/performance/mlperf-run", true));
});

test("rejects invalid duration, data and timeout before preview", () => {
  expect(validateGuidedPerformance({ ...base, duration: 0 })).toMatch(/时长/);
  expect(validateGuidedPerformance({ ...base, dataset: 0 })).toMatch(/数据量/);
  expect(validateGuidedPerformance({ ...base, timeoutMinutes: 1 })).toMatch(/超时/);
  expect(validateGuidedPerformance({ ...base, blockSize: 512, blockUnit: "MiB" })).toMatch(/块大小/);
});

test("changing machine clears a mount that belongs to the previous machine", async () => {
  vi.mocked(api).mockResolvedValue(options);
  render(<GuidedPerformanceFlow onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("测试位置"), { target: { value: "mount" } });
  fireEvent.change(screen.getByLabelText("挂载目录"), { target: { value: "/mnt/one" } });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m2" } });
  expect(screen.getByLabelText("挂载目录")).toHaveValue("");
  expect(screen.getByText("这台机器暂无可用的已挂载文件系统。")).toBeTruthy();
});

test("accepts dots inside a directory name but rejects a parent directory component", async () => {
  vi.mocked(api).mockResolvedValue(options);
  render(<GuidedPerformanceFlow onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/mnt/data/../other" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("alert")).toHaveTextContent("绝对目标目录");
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/mnt/data/v1..v2" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("heading", { name: "选择工具" })).toBeTruthy();
});

test("cleanup option describes combined data as occupancy, not retained data", async () => {
  vi.mocked(api).mockResolvedValue(options);
  render(<GuidedPerformanceFlow onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/data" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByLabelText("fio"));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByText("高级选项"));
  fireEvent.click(screen.getByLabelText("全部成功后清理任务数据"));
  expect(screen.getByText(/预计数据占用：1 GiB/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText("预计数据占用")).toBeTruthy();
  expect(screen.queryByText("合计保留数据")).toBeNull();
});

test("moves through location, tools, parameters and confirmation; edits invalidate preview", async () => {
  vi.mocked(api).mockImplementation(async (path) => path === "/performance/options" ? options :
    path === "/performance/preview" ? { total_bytes: 1073741824, tests: [{ tool: "fio", command: "dtt fio", parameters: {} }] } : []);
  render(<GuidedPerformanceFlow onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/data" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByLabelText("fio"));
  fireEvent.click(screen.getByLabelText("elbencho"));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText(/预计数据占用/)).toHaveTextContent("2 GiB");
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
  await screen.findByText("dtt fio");
  fireEvent.click(screen.getByRole("button", { name: "上一步" }));
  fireEvent.change(screen.getByLabelText("测量时长"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("button", { name: "开始测试" })).toBeDisabled();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/performance/preview", "POST", expect.objectContaining({ tests: expect.any(Array) })));
});

test("starts once and navigates only after confirmed response", async () => {
  let resolveRun!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (path) => path === "/performance/options" ? options :
    path === "/performance/preview" ? { total_bytes: 1073741824, tests: [{ tool: "fio", command: "dtt fio", parameters: {} }] } :
    path === "/performance/runs" ? new Promise(resolve => { resolveRun = resolve; }) : []);
  const navigate = vi.fn();
  render(<GuidedPerformanceFlow onNavigate={navigate} onDirty={vi.fn()} />);
  await screen.findByRole("option", { name: /主机一/ });
  fireEvent.change(screen.getByLabelText("目标机器"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("目标目录"), { target: { value: "/data" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByLabelText("fio"));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
  await screen.findByText("dtt fio");
  fireEvent.click(screen.getByRole("button", { name: "开始测试" }));
  fireEvent.click(screen.getByRole("button", { name: "开始测试" }));
  expect(navigate).not.toHaveBeenCalled();
  expect(vi.mocked(api).mock.calls.filter(call => call[0] === "/performance/runs")).toHaveLength(1);
  resolveRun({ id: "run-1" });
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("#/performance/run-1", true));
});
