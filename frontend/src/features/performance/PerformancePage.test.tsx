import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { PerformancePage } from "./PerformancePage";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks();
  window.location.hash = "#/performance";
});
function selectValues(label: string, values: string[]) {
  const group = screen.getByRole("group", { name: label });
  for (const button of within(group).queryAllByRole("button"))
    fireEvent.click(button);
  for (const value of values) {
    const container = group.closest(".performance-candidates") as HTMLElement;
    const preset = within(container).queryByRole("button", { name: value });
    if (preset) fireEvent.click(preset);
    else {
      fireEvent.change(screen.getByLabelText(label + "自定义值"), {
        target: { value },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "添加 " + label + "自定义值" }),
      );
    }
  }
}
const options = {
  machines: [
    {
      id: "node",
      name: "机器128",
      address: "172.30.14.128",
      ssh_user: "jenkins",
      maintenance: false,
    },
  ],
  mounts: [],
};

test("select multiple tools with independent settings and preview before create", async () => {
  vi.mocked(api).mockImplementation(async (path, method) =>
    path === "/performance/options"
      ? options
      : path === "/performance/runs" && method !== "POST"
        ? []
        : path === "/performance/preview"
          ? {
              total_bytes: 2048,
              tests: [{ tool: "fio", command: "dtt -t fio" }],
            }
          : {
              id: "run",
              state: "queued",
              snapshot: { tests: [] },
              reports: {},
            },
  );
  render(<PerformancePage />);
  fireEvent.click(screen.getByRole("button", { name: "新建测试" }));
  fireEvent.click(screen.getByRole("button", { name: "添加工具" }));
  await screen.findByRole("option", { name: /机器128/ });
  fireEvent.change(screen.getByLabelText("目标机器"), {
    target: { value: "node" },
  });
  fireEvent.change(screen.getByLabelText("目标目录"), {
    target: { value: "/mnt/test" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加工具" }));
  expect(screen.getByLabelText("测试完成后清理测试数据")).not.toBeChecked();
  fireEvent.click(screen.getByLabelText("测试完成后清理测试数据"));
  selectValues("并发线程数", ["2"]);
  expect(screen.queryByRole("button", { name: "确认并开始测试" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "预览执行计划" }));
  await screen.findByRole("button", { name: "确认并开始测试" });
  const call = vi
    .mocked(api)
    .mock.calls.find((c) => c[0] === "/performance/preview");
  expect(call?.[2]).toMatchObject({
    cleanup_data: true,
    machine_id: "node",
    target_path: "/mnt/test",
    tests: [
      { tool: "elbencho", concurrency: [2] },
      { tool: "fio", concurrency: [4] },
    ],
  });
  fireEvent.change(screen.getByLabelText("目标目录"), {
    target: { value: "/mnt/changed" },
  });
  expect(screen.queryByRole("button", { name: "确认并开始测试" })).toBeNull();
});

test("shows failure and captured report without treating it as success", async () => {
  window.location.hash = "#/performance/job";
  const row = {
    id: "job",
    name: "失败任务",
    state: "failed",
    phase: "执行失败",
    error: "fio退出码7",
    progress: 0,
    can_manage: false,
    created_at: new Date().toISOString(),
    snapshot: {
      machine_name: "128",
      connection: ["host", 22, "jenkins"],
      target_path: "/tmp",
      tests: [{ tool: "fio" }],
    },
    reports: {
      fio: {
        summary: { status: "failed" },
        files: ["index.html"],
        remote_path: "/tmp/report",
      },
    },
  };
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/performance/options"
      ? options
      : path === "/performance/runs"
        ? []
        : row,
  );
  render(<PerformancePage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("fio退出码7");
  fireEvent.click(screen.getByRole("button", { name: "查看报告" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看网页报告" }));
  expect(screen.queryByRole("heading", { name: "测试任务与报告" })).toBeNull();
  expect(screen.queryByText("执行命令和实时日志（显示最近128KiB）")).toBeNull();
  expect(screen.getByTitle("fio 性能报告")).toHaveAttribute(
    "sandbox",
    "allow-scripts",
  );
  expect(screen.queryByRole("button", { name: "取消测试" })).toBeNull();
});

test("multiple parameter values preview distinct scenes and invalidate after edit", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/performance/options"
      ? options
      : path === "/performance/preview"
        ? {
            scene_count: 4,
            total_bytes: 4096,
            tests: [1, 2, 3, 4].map((i) => ({
              id: `scene-${i}-fio`,
              tool: "fio",
              parameters: {
                rw: "write",
                direct: true,
                concurrency: i,
                file_size: "4096",
                file_count: 4,
                block_size: "4096",
                rounds: 1,
                iodepth: 1,
              },
              command: `dtt scenario ${i}`,
            })),
          }
        : [],
  );
  render(<PerformancePage />);
  fireEvent.click(screen.getByRole("button", { name: "新建测试" }));
  fireEvent.click(screen.getByRole("button", { name: "添加工具" }));
  await screen.findByRole("option", { name: /机器128/ });
  fireEvent.change(screen.getByLabelText("目标机器"), {
    target: { value: "node" },
  });
  fireEvent.change(screen.getByLabelText("目标目录"), {
    target: { value: "/tmp/matrix" },
  });
  selectValues("并发作业数", ["4", "1"]);
  selectValues("Block 大小", ["1MiB", "4KiB"]);
  fireEvent.click(screen.getByRole("button", { name: "预览执行计划" }));
  await screen.findByRole("button", { name: "确认并开始测试" });
  expect(
    vi.mocked(api).mock.calls.find((c) => c[0] === "/performance/preview")?.[2],
  ).toMatchObject({
    tests: [{ concurrency: [1, 4], block_size: ["4KiB", "1MiB"] }],
  });
  expect(screen.getByText(/共 4 个场景/)).toBeInTheDocument();
  selectValues("并发作业数", ["4", "2", "1"]);
  expect(screen.queryByRole("button", { name: "确认并开始测试" })).toBeNull();
});

test("rerun requires confirmation and creates a new task", async () => {
  const original = {
    id: "original",
    name: "原任务",
    state: "failed",
    can_manage: true,
    progress: 100,
    created_at: new Date().toISOString(),
    snapshot: {
      machine_name: "126",
      connection: ["host", 22, "jenkins"],
      target_path: "/tmp/test",
      tests: [],
    },
    reports: {},
  };
  const next = {
    ...original,
    id: "new",
    name: "原任务 · 重跑",
    state: "queued",
    phase: "等待执行",
    deadline: new Date().toISOString(),
  };
  vi.mocked(api).mockImplementation(async (path, method) =>
    path === "/performance/options"
      ? options
      : path === "/performance/runs"
        ? [original]
        : path === "/performance/runs/original/rerun" && method === "POST"
          ? next
          : next,
  );
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<PerformancePage />);
  await screen.findByRole("button", { name: "重跑" });
  fireEvent.click(screen.getByRole("button", { name: "重跑" }));
  expect(vi.mocked(api).mock.calls.some((c) => c[0].endsWith("/rerun"))).toBe(
    false,
  );
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "重跑" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/performance/runs/original/rerun",
      "POST",
    ),
  );
  await screen.findByRole("heading", { name: "原任务 · 重跑" });
  expect(window.location.hash).toBe("#/performance/new");
  confirm.mockRestore();
});

test("new task starts empty, prepends tools, preserves prior settings and supports delete and return", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/performance/options" ? options : [],
  );
  render(<PerformancePage />);
  fireEvent.click(screen.getByRole("button", { name: "新建测试" }));
  expect(screen.queryByRole("heading", { name: "fio" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "测试任务与报告" })).toBeNull();
  expect(screen.queryByRole("button", { name: "新建测试" })).toBeNull();
  expect(screen.getByRole("button", { name: "预览执行计划" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "添加工具" }));
  selectValues("并发作业数", ["8"]);
  fireEvent.change(screen.getByLabelText("选择工具"), {
    target: { value: "elbencho" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加工具" }));
  const titles = screen
    .getAllByRole("heading", { level: 3 })
    .map((h) => h.textContent);
  expect(titles.indexOf("elbencho")).toBeLessThan(titles.indexOf("fio"));
  expect(
    screen.getByRole("list", { name: "并发作业数已选值" }),
  ).toHaveTextContent("8");
  fireEvent.click(screen.getByRole("button", { name: "删除 elbencho" }));
  expect(screen.queryByRole("heading", { name: "elbencho" })).toBeNull();
  expect(screen.getByRole("heading", { name: "fio" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回" }));
  expect(
    screen.getByRole("heading", { name: "测试任务与报告" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "配置测试" })).toBeNull();
  expect(window.location.hash).toBe("#/performance");
});
