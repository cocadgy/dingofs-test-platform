import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../../api/client";
import { FunctionalPage } from "./FunctionalPage";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
const opts = {
  digest: "a".repeat(64),
  clusters: [
    { id: "c1", name: "集群1" },
    { id: "c2", name: "集群2" },
  ],
  environments: [],
  modules: {
    basic_file_operation: [
      { path: "a.yaml", name: "用例A" },
      { path: "b.yaml", name: "用例B" },
    ],
    dirstat: [{ path: "delta/c.yaml", name: "用例C" }],
  },
};
const profiles = [
  {
    id: "p1",
    name: "环境1",
    revision: 2,
    enabled: true,
    source_kind: "custom",
    cluster_id: "c1",
  },
  {
    id: "p2",
    name: "环境2",
    revision: 1,
    enabled: true,
    source_kind: "custom",
    cluster_id: "c2",
  },
];
const complete = {
  id: "done",
  name: "已完成任务",
  state: "success",
  phase: "已完成",
  progress: 100,
  error: "",
  created_at: new Date().toISOString(),
  snapshot: {
    cluster_id: "c1",
    selected: { basic_file_operation: ["a.yaml"] },
  },
  result: {
    cases: [{ module: "basic_file_operation", case: "a.yaml", status: "PASS" }],
  },
  log: "test log",
};
beforeEach(() => {
  window.location.hash = "#/functional/new";
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/options") return opts;
    if (path === "/functional/environments") return profiles;
    if (path === "/functional/runs" && method === "POST")
      return { ...complete, id: "new", state: "queued" };
    if (path === "/functional/runs") return [complete];
    if (path === "/functional/runs/done") return complete;
    if (path === "/functional/runs/new")
      return { ...complete, id: "new", state: "running" };
    return {};
  });
});
test("selecting and deselecting module submits exact paths and profile revision", async () => {
  render(<FunctionalPage />);
  const all = await screen.findByRole("checkbox", {
    name: "选择 basic_file_operation 全部用例",
  });
  fireEvent.click(all);
  expect(screen.getByText("已选 2 项")).toBeInTheDocument();
  fireEvent.click(all);
  expect(screen.getByText("已选 0 项")).toBeInTheDocument();
  fireEvent.click(all);
  const start = screen.getByRole("button", { name: "启动 2 个用例" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.find(
          (c) => c[0] === "/functional/runs" && c[1] === "POST",
        )?.[2],
    ).toMatchObject({
      cluster_id: "c1",
      environment_profile_id: "p1",
      environment_profile_revision: 2,
      selected: { basic_file_operation: ["a.yaml", "b.yaml"] },
    }),
  );
});
test("changing cluster clears the previous environment instead of keeping a hidden choice", async () => {
  render(<FunctionalPage />);
  const selects = await screen.findAllByRole("combobox");
  await waitFor(() => expect(selects[1]).toHaveValue("p1"));
  fireEvent.change(selects[0], { target: { value: "c2" } });
  await waitFor(() => expect(selects[1]).toHaveValue(""));
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  );
  expect(screen.getByRole("button", { name: "启动 2 个用例" })).toBeDisabled();
  expect(
    vi
      .mocked(api)
      .mock.calls.some((c) =>
        String(c[0]).includes("/p1/validate?cluster_id=c2"),
      ),
  ).toBe(false);
});
test("successful task disables failed-case rerun and opens report in a new tab", async () => {
  window.location.hash = "#/functional/done";
  render(<FunctionalPage />);
  const report = await screen.findByRole("link", { name: /打开 Allure 报告/ });
  expect(report).toHaveAttribute("target", "_blank");
  expect(screen.getByRole("button", { name: "重跑失败用例" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "执行日志" }));
  expect(screen.getByText("test log")).toBeInTheDocument();
});
test("invalid environment blocks submission and exposes the reason", async () => {
  const previous = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (String(path).includes("/validate?")) throw new Error("测试环境已停用");
    return previous(path, ...args);
  });
  render(<FunctionalPage />);
  await screen.findByText("环境不适用：测试环境已停用");
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  );
  expect(screen.getByRole("button", { name: "启动 2 个用例" })).toBeDisabled();
});

test("list is separate from creation and task routes survive direct navigation", async () => {
  window.location.hash = "#/functional";
  render(<FunctionalPage />);
  expect(
    await screen.findByRole("button", { name: "已完成任务" }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("任务名称")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "已完成任务" }));
  await waitFor(() => expect(window.location.hash).toBe("#/functional/done"));
});
test("switching task hides stale detail and actions while the new task loads", async () => {
  window.location.hash = "#/functional/done";
  render(<FunctionalPage />);
  await screen.findByRole("link", { name: /打开 Allure 报告/ });
  const prior = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, ...args) =>
    path === "/functional/runs/slow"
      ? new Promise(() => {})
      : prior(path, ...args),
  );
  window.location.hash = "#/functional/slow";
  fireEvent(window, new HashChangeEvent("hashchange"));
  await waitFor(() =>
    expect(
      screen.queryByRole("link", { name: /打开 Allure 报告/ }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("button", { name: "重跑全部" }),
  ).not.toBeInTheDocument();
});
test("case search preserves selected hidden cases and shows partial module selection", async () => {
  render(<FunctionalPage />);
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  );
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索用例" }), {
    target: { value: "用例A" },
  });
  expect(screen.queryByText("用例B")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /用例A/ }));
  expect(screen.getByText("已选 1 项")).toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  ).toBePartiallyChecked();
});
