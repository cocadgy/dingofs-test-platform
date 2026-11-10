import { expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RunDetail } from "./RunDetail";
import { RunList } from "./RunList";
import { FunctionalPage } from "./FunctionalPage";
import { api } from "../../api/client";
import type { Run, ModuleRunView, ChildResult } from "./types";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

const result = (overrides: Partial<ChildResult> = {}): ChildResult => ({
  child_state: "success",
  stage: "completed",
  case_counts: { passed: 1, failed: 0, skipped: 0, known_bugs: 0, completed: 1, total: 1 },
  case_results: [{ case_path: "a.yaml", attempt: 2, status: "PASS" }],
  attempt_records: [
    { case_path: "a.yaml", attempt: 1, status: "FAIL", seq: 3 },
    { case_path: "a.yaml", attempt: 2, status: "PASS", seq: 5 },
  ],
  failed_cases: [], missing: [], not_run: [], suite_errors: 0,
  cleanup_status: "cleaned", recovery_status: "recovered", retained_resources: [],
  report_status: "ready", report_path: "integration_123/basic_file_operation/report/index.html",
  may_continue: true, end_proof: true,
  ...overrides,
});
const child = (overrides: Partial<ModuleRunView> = {}): ModuleRunView => ({
  id: "child-one", module: "basic_file_operation", position: 0,
  env_name: "环境旧名", state: "success", stage: "completed",
  execution_targets: [{ machine_id: "machine-1", name: "机器旧名", ip: "10.0.0.7", user: "tester" }],
  events: [], environment_snapshot: {}, cases: ["a.yaml"],
  started_at: "2026-11-10T08:00:00Z", deadline: null, finished_at: "2026-11-10T08:01:00Z",
  result: result(), error: "", ...overrides,
});
const v2 = (overrides: Partial<Run> = {}): Run => ({
  id: "parent-one", name: "模块任务", version: 2, can_manage: true,
  state: "success", phase: "已完成", progress: 100, error: "", log: "parent log",
  snapshot: { selected: { basic_file_operation: ["a.yaml"] }, cluster_name: "旧集群" },
  created_at: "2026-11-10T08:00:00Z", finished_at: "2026-11-10T08:01:00Z",
  children: [child()], ...overrides,
});
const show = (run: Run) => render(<RunDetail run={run} busy={false} onStop={vi.fn()} onRerun={vi.fn()} />);

test.each(['cancelling', 'needs_attention', 'cancelled'])("timeout cause is visible in parent and child during %s", state => {
  show(v2({state, termination_cause: 'timeout', children: [child({state, termination_cause: 'timeout',
    result: result({termination_cause: 'timeout'})})]}));
  expect(screen.getByText('终止原因：达到执行时限')).toBeInTheDocument();
  fireEvent.click(screen.getByText('基础文件操作'));
  expect(within(screen.getByRole('region', {name: '基础文件操作'})).getByText('模块终止原因：达到执行时限')).toBeInTheDocument();
});

test('manual cancellation remains visibly distinct from deadline termination', () => {
  show(v2({state: 'cancelled', termination_cause: 'manual'}));
  expect(screen.getByText('终止原因：用户停止')).toBeInTheDocument();
  expect(screen.queryByText(/达到执行时限/)).not.toBeInTheDocument();
});

test("test_setup_has_machine_ip_user_before_cases", () => {
  show(v2({ children: [child({ stage: "setup" })] }));
  fireEvent.click(screen.getByText("基础文件操作"));
  const module = screen.getByRole("region", { name: "基础文件操作" });
  const text = module.textContent || "";
  expect(text).toContain("机器旧名");
  expect(text).toContain("10.0.0.7");
  expect(text).toContain("tester");
  expect(text.indexOf("10.0.0.7")).toBeLessThan(text.indexOf("a.yaml"));
});

test("test_final_attempt_counts_once", () => {
  show(v2());
  expect(screen.getByText("1 / 1")).toBeInTheDocument();
  fireEvent.click(screen.getByText("基础文件操作"));
  const module = screen.getByRole("region", { name: "基础文件操作" });
  expect(within(module).getByText("第 1 次 · 失败")).toBeInTheDocument();
  expect(within(module).getByText("第 2 次 · 通过")).toBeInTheDocument();
  expect(within(module).getByText("最终：通过")).toBeInTheDocument();
});

test("test_remaining_modules_not_run", () => {
  const waiting = child({
    id: "child-two", module: "quota", position: 1, state: "queued", stage: "waiting",
    cases: ["b.yaml"], result: result({ child_state: "queued", stage: "waiting",
      case_counts: { passed: 0, failed: 0, skipped: 0, known_bugs: 0, completed: 0, total: 1 },
      case_results: [], attempt_records: [], not_run: ["b.yaml"],
      report_status: "pending", report_path: null, may_continue: false, end_proof: false }),
  });
  show(v2({ state: "running", finished_at: undefined, children: [child(), waiting] }));
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  fireEvent.click(screen.getByText("配额"));
  expect(within(screen.getByRole("region", { name: "配额" })).getByText("b.yaml")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "配额" })).getByText(/未执行/)).toBeInTheDocument();
});

test("test_child_report_failure_is_not_pass_link", () => {
  const failedReport = child({ result: result({ report_status: "failed", report_path: null }) });
  show(v2({ children: [failedReport] }));
  fireEvent.click(screen.getByText("基础文件操作"));
  expect(screen.getByText("报告生成失败")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Allure/ })).not.toBeInTheDocument();
});

test("ready child report link includes parent and child ids", () => {
  show(v2());
  fireEvent.click(screen.getByText("基础文件操作"));
  expect(screen.getByRole("link", { name: /Allure/ })).toHaveAttribute(
    "href", "/api/v1/functional/runs/parent-one/modules/child-one/report/index.html",
  );
});

test("test_legacy_run_without_children_still_renders", () => {
  show({ id: "old", name: "历史任务", state: "success", phase: "已完成", progress: 100,
    error: "", created_at: "2026-11-10T08:00:00Z",
    snapshot: { selected: { quota: ["old.yaml"] } },
    result: { cases: [{ module: "quota", case: "old.yaml", status: "PASS" }] } });
  expect(screen.getByText("历史任务")).toBeInTheDocument();
  expect(screen.getByText("old.yaml")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重跑全部" })).toBeDisabled();
});

test("active legacy run keeps its stop action", () => {
  const onStop = vi.fn();
  render(<RunDetail run={{ id: "legacy-running", name: "旧任务", state: "running",
    phase: "执行中", progress: 25, error: "", created_at: "2026-11-10T08:00:00Z",
    snapshot: { selected: { quota: ["a.yaml"] } },
  }} busy={false} onStop={onStop} onRerun={vi.fn()} />);
  const stop = screen.getByRole("button", { name: /停止测试/ });
  expect(stop).toBeEnabled();
  fireEvent.click(stop);
  expect(onStop).toHaveBeenCalledOnce();
  expect(screen.queryByText("历史任务只读")).not.toBeInTheDocument();
});

test("cancelling and unknown children never say stopped or offer rerun", () => {
  show(v2({ state: "cancelling", finished_at: undefined, children: [child({
    state: "cancelling", result: result({ child_state: "cancelling", end_proof: false }),
  })] }));
  expect(screen.getAllByText("正在停止").length).toBeGreaterThan(0);
  expect(screen.queryByText("已停止")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /重跑/ })).not.toBeInTheDocument();
});

test("v2 without write authority offers no actions", () => {
  show(v2({ can_manage: undefined }));
  expect(screen.queryByRole("button", { name: /重跑/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /停止测试/ })).not.toBeInTheDocument();
});

test("V2 without a frozen child or machine scope cannot offer rerun", () => {
  show(v2({ children: [] }));
  expect(screen.queryAllByRole("button", { name: /重跑/ })).toHaveLength(0);
});

test("queued V2 child with no result does not invent success or progress", () => {
  show(v2({ state: "queued", finished_at: undefined, children: [child({
    state: "queued", cases: ["a.yaml", "b.yaml"], result: {},
  })] }));
  expect(screen.getByText("— / 2")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("基础文件操作"));
  expect(screen.getByText("用例数量待确认")).toBeInTheDocument();
  expect(screen.getAllByText("结果待确认")).toHaveLength(2);
  expect(screen.getByText("报告状态待确认")).toBeInTheDocument();
});

test("ready report with an unsafe or non HTML path does not become a link", () => {
  show(v2({ children: [child({ result: result({ report_path: "../allure-results" }) })] }));
  fireEvent.click(screen.getByText("基础文件操作"));
  expect(screen.queryByRole("link", { name: /Allure/ })).not.toBeInTheDocument();
});

test("V2 history list shows completed modules without counting queued modules", () => {
  render(<RunList runs={[v2({ state: "running", children: [child(), child({
    id: "child-two", module: "quota", position: 1, state: "queued", result: {},
  })] })]} onOpen={vi.fn()} />);
  expect(screen.getByText("1 / 2 模块已结束")).toBeInTheDocument();
});

test("inconsistent V2 counts do not display an invented completed percentage", () => {
  show(v2({ children: [child({ result: result({ case_counts: {
    passed: 3, failed: 0, skipped: 0, known_bugs: 0, completed: 3, total: 3,
  } }) })] }));
  expect(screen.getByText("— / 1")).toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("failed-only rerun is unavailable without an explicit final failed case", () => {
  show(v2({ state: "failed", children: [child({ state: "failed", result: result({
    child_state: "failed", case_counts: {
      passed: 0, failed: 1, skipped: 0, known_bugs: 0, completed: 1, total: 1,
    }, case_results: [{ case_path: "a.yaml", attempt: 2, status: "FAIL" }], failed_cases: [],
  }) })] }));
  expect(screen.getByRole("button", { name: "重跑失败用例" })).toBeDisabled();
});

test("V2 rerun confirms frozen module and machine scope and keeps one key for a retry", async () => {
  window.location.hash = "#/functional/parent-one";
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(api).mockReset();
  let rerunCalls = 0;
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/options") return { clusters: [], modules: {}, digest: "x" };
    if (path === "/functional/environments") return [];
    if (path === "/functional/runs/parent-one") return v2({ state: "failed", children: [child({
      state: "failed", result: result({ child_state: "failed", case_counts: {
        passed: 0, failed: 1, skipped: 0, known_bugs: 0, completed: 1, total: 1,
      }, case_results: [{ case_path: "a.yaml", attempt: 2, status: "FAIL" }], failed_cases: ["a.yaml"] }),
    })] });
    if (method === "POST" && String(path).includes("/rerun")) {
      rerunCalls += 1;
      if (rerunCalls === 1) throw new Error("暂时不可用");
      return { id: "next" };
    }
    return [];
  });
  render(<FunctionalPage />);
  const button = await screen.findByRole("button", { name: "重跑失败用例" });
  fireEvent.click(button);
  await screen.findByText("暂时不可用");
  fireEvent.click(button);
  await waitFor(() => expect(rerunCalls).toBe(2));
  const calls = vi.mocked(api).mock.calls.filter(([path, method]) => method === "POST" && String(path).includes("/rerun"));
  expect(calls[0][0]).toBe("/functional/runs/parent-one/rerun?failed_only=true");
  expect(calls[0][2]).toEqual({ idempotency_key: expect.any(String) });
  expect(calls[1][2]).toEqual(calls[0][2]);
  expect(confirm.mock.calls[0][0]).toContain("基础文件操作");
  expect(confirm.mock.calls[0][0]).toContain("机器旧名");
  expect(confirm.mock.calls[0][0]).toContain("10.0.0.7");
  confirm.mockRestore();
});

test("successful V2 rerun then returning creates a new idempotency key", async () => {
  window.location.hash = "#/functional/parent-one";
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(api).mockReset();
  let reruns = 0;
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/options") return { clusters: [], modules: {}, digest: "x" };
    if (path === "/functional/environments") return [];
    if (path === "/functional/runs/parent-one") return v2();
    if (path === "/functional/runs/next") return v2({ id: "next" });
    if (method === "POST" && String(path).includes("/rerun")) return { id: ++reruns === 1 ? "next" : "next-two" };
    return [];
  });
  render(<FunctionalPage />);
  fireEvent.click(await screen.findByRole("button", { name: "重跑全部" }));
  await waitFor(() => expect(window.location.hash).toBe("#/functional/next"));
  window.location.hash = "#/functional/parent-one";
  fireEvent(window, new HashChangeEvent("hashchange"));
  fireEvent.click(await screen.findByRole("button", { name: "重跑全部" }));
  await waitFor(() => expect(reruns).toBe(2));
  const keys = vi.mocked(api).mock.calls
    .filter(([path, method]) => method === "POST" && String(path).includes("/rerun"))
    .map(([, , body]) => (body as { idempotency_key: string }).idempotency_key);
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe(keys[1]);
  confirm.mockRestore();
});

test("declining V2 rerun scope sends no mutation", async () => {
  window.location.hash = "#/functional/parent-one";
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/functional/options") return { clusters: [], modules: {}, digest: "x" };
    if (path === "/functional/environments") return [];
    if (path === "/functional/runs/parent-one") return v2();
    return [];
  });
  render(<FunctionalPage />);
  fireEvent.click(await screen.findByRole("button", { name: "重跑全部" }));
  expect(vi.mocked(api).mock.calls.some(([path, method]) => method === "POST" && String(path).includes("/rerun"))).toBe(false);
  confirm.mockRestore();
});
