import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ScenarioParameters } from "./ScenarioParameters";
import { ReportCards } from "./ReportCards";
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
