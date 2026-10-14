import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { ScenarioResults } from "./ScenarioResults";
import { Run, Spec } from "./types";
test("same tool scenarios display independent metrics reports and state filter", () => {
  const spec = {
    tool: "fio",
    direct: true,
    concurrency: 1,
    file_size: "4096",
    file_count: 1,
    block_size: "4096",
    rw: "write",
    rounds: 1,
    iodepth: 1,
  } as Spec;
  const run = {
    id: "job",
    snapshot: {
      scenarios: [
        { id: "scene-001-fio", tool: "fio", parameters: spec },
        {
          id: "scene-002-fio",
          tool: "fio",
          parameters: { ...spec, concurrency: 2 },
        },
      ],
    },
    reports: {
      "scene-001-fio": {
        state: "success",
        files: ["index.html"],
        summary: {
          status: "passed",
          statistics: { metrics: { bandwidth_mib_s: { mean: 12.3 } } },
        },
      },
      "scene-002-fio": { state: "failed", files: [], error: "磁盘空间不足" },
    },
  } as unknown as Run;
  render(<ScenarioResults run={run} />);
  expect(screen.getByText("12.30")).toBeInTheDocument();
  const rows = screen.getAllByRole("row");
  fireEvent.click(within(rows[1]).getByRole("button", { name: "查看报告" }));
  expect(window.location.hash).toBe("#/performance/job/reports/scene-001-fio");
  expect(screen.queryByTitle("scene-001-fio 性能报告")).toBeNull();
  expect(
    within(rows[2]).getByRole("button", { name: "查看报告" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("场景状态"), {
    target: { value: "failed" },
  });
  expect(screen.getAllByRole("row")).toHaveLength(2);
  expect(screen.getByText("磁盘空间不足")).toBeInTheDocument();
});
