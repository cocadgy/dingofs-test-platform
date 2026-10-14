import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { TaskTable } from "./TaskTable";
import { Run } from "./types";
test("task table filters results and only finished manageable tasks can rerun", () => {
  const base = {
    progress: 100,
    created_at: new Date().toISOString(),
    snapshot: {
      machine_name: "126",
      target_path: "/mnt/perf",
      tests: [{ tool: "fio" }],
    },
  };
  const runs = [
    { ...base, id: "a", name: "完成任务", state: "success", can_manage: true },
    { ...base, id: "b", name: "执行任务", state: "running", can_manage: true },
    { ...base, id: "c", name: "他人任务", state: "failed", can_manage: false },
  ] as Run[];
  const rerun = vi.fn();
  render(<TaskTable runs={runs} selected="a" busy={false} onRerun={rerun} />);
  const rows = screen.getAllByRole("row");
  fireEvent.click(within(rows[1]).getByRole("button", { name: "重跑" }));
  expect(rerun).toHaveBeenCalledWith(runs[0]);
  expect(within(rows[2]).getByRole("button", { name: "重跑" })).toBeDisabled();
  expect(within(rows[3]).queryByRole("button", { name: "重跑" })).toBeNull();
  fireEvent.change(screen.getByLabelText("任务状态"), {
    target: { value: "failed" },
  });
  expect(screen.getAllByRole("row")).toHaveLength(2);
  fireEvent.change(screen.getByLabelText("搜索测试任务"), {
    target: { value: "missing" },
  });
  expect(screen.getByText("没有匹配的任务")).toBeInTheDocument();
});
