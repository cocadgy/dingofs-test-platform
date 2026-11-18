import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ScenarioParameters } from "./ScenarioParameters";
import { ReportCards } from "./ReportCards";
import { ScenarioResults } from "./ScenarioResults";
import type { Run, Spec } from "./types";

afterEach(cleanup);
const spec: Spec = { tool: "fio", direct: true, concurrency: 4, file_size: "268435456", file_count: 4,
  total_size: "1073741824", block_size: "4096", rw: "write", rounds: 2, iodepth: 1,
  read_percent: 0, runtime_seconds: 120 };

test("scenario parameters show requested duration only for timed workloads", () => {
  const { rerender } = render(<ScenarioParameters spec={spec} />);
  expect(screen.getByText(/每轮测量 120 秒/)).toBeTruthy();
  rerender(<ScenarioParameters spec={{ ...spec, runtime_seconds: undefined }} />);
  expect(screen.queryByText(/每轮测量/)).toBeNull();
});

test("timed report distinguishes dataset size from actual I/O and measured time", () => {
  const run: Run = { id: "r1", name: "timed", state: "success", phase: "completed", progress: 1,
    error: "", created_at: "2026-11-17T00:00:00Z", deadline: "2026-11-17T02:00:00Z", can_manage: true,
    cancel_requested: false, reports: { fio: { tool: "fio", parameters: spec, files: [], remote_path: "/tmp/report", command: "dtt fio",
    summary: { status: "passed", statistics: { successful_rounds: 2, requested_rounds: 2, metrics: {
      measurement_seconds: { mean: 119.8, samples: 2 }, io_bytes: { mean: 2147483648, samples: 2 },
    } } } } }, snapshot: { tests: [spec], machine_name: "机器", connection: ["192.0.2.1", 22, "test"], target_path: "/mnt/test", target_kind: "mount" } };
  render(<ReportCards run={run} />);
  expect(screen.getByText(/请求每轮测量：120 秒/)).toBeTruthy();
  expect(screen.getByText(/每轮实际测量：119.8 秒/)).toBeTruthy();
  expect(screen.getByText(/每轮实际 I\/O：2 GiB/)).toBeTruthy();
  expect(screen.getByText(/每工具数据集：1 GiB/)).toBeTruthy();
});

test("MLPerf report shows training throughput and utilization without invented fio metrics", () => {
  const mlperf: Spec = { ...spec, tool: "mlperf", runtime_seconds: null, mlperf_model: "resnet50",
    mlperf_epochs: 5, mlperf_accelerators: 2, concurrency: 4, file_count: 8,
    file_size: "143439748", total_size: "1147517984", block_size: "0", rw: "read", direct: false };
  const run: Run = { id: "m1", name: "mlperf", state: "success", phase: "done", progress: 1,
    error: "", created_at: "2026-11-18T00:00:00Z", deadline: "2026-11-18T02:00:00Z",
    can_manage: true, cancel_requested: false, reports: { mlperf: { tool: "mlperf", parameters: mlperf,
      files: ["index.html", "summary.json"], remote_path: "/tmp/mlperf", command: "dtt -t mlperf",
      summary: { status: "passed", statistics: { successful_rounds: 1, requested_rounds: 1,
        metrics: { samples_per_second: { mean: 123.4, samples: 1 }, accelerator_utilization_percent: { mean: 88.5, samples: 1 } } } } } },
    snapshot: { tests: [mlperf], machine_name: "主机", connection: ["192.0.2.1", 22, "test"], target_path: "/data", target_kind: "directory" } };
  const { container } = render(<><ScenarioParameters spec={mlperf} /><ReportCards run={run} /></>);
  expect(container.textContent).toContain("ResNet50");
  expect(container.textContent).toContain("5 epochs");
  expect(container.textContent).toContain("2 个模拟 H100");
  expect(screen.getByText("平均训练吞吐")).toBeTruthy();
  expect(screen.getByText("平均加速器利用率")).toBeTruthy();
  expect(container.textContent).not.toContain("平均 IOPS");
  expect(container.textContent).not.toContain("平均延迟");
  expect(container.textContent).not.toContain("每轮实际测量：0 秒");
  expect(screen.getByRole("link", { name: "JSON 报告" })).toHaveAttribute("href", "/api/v1/performance/runs/m1/reports/mlperf/summary.json");
});

test("MLPerf scenario table uses training metrics instead of fio metrics", () => {
  const mlperf: Spec = { ...spec, tool: "mlperf", runtime_seconds: null, mlperf_model: "unet3d",
    mlperf_epochs: 5, mlperf_accelerators: 1 };
  const run: Run = { id: "m1", name: "training", state: "success", phase: "done", progress: 1,
    error: "", created_at: "2026-11-18T00:00:00Z", deadline: "2026-11-18T02:00:00Z",
    can_manage: true, cancel_requested: false, reports: { mlperf: { tool: "mlperf", parameters: mlperf,
      files: ["summary.json"], remote_path: "/tmp/mlperf", command: "dtt -t mlperf",
      summary: { status: "passed", statistics: { successful_rounds: 1, requested_rounds: 1,
        metrics: { samples_per_second: { mean: 25, samples: 1 }, accelerator_utilization_percent: { mean: 80, samples: 1 } } } } } },
    snapshot: { tests: [mlperf], machine_name: "主机", connection: ["192.0.2.1", 22, "test"], target_path: "/data", target_kind: "directory" } };
  render(<ScenarioResults run={run} />);
  expect(screen.getByRole("columnheader", { name: "训练吞吐 samples/s" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "加速器利用率 %" })).toBeTruthy();
  expect(screen.queryByRole("columnheader", { name: /IOPS/ })).toBeNull();
  expect(screen.getByRole("cell", { name: "25.00" })).toBeTruthy();
});
