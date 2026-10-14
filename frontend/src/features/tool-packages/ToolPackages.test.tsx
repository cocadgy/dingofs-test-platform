import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ToolPackagesPage } from "./ToolPackagesPage";
import { MachineTools } from "./MachineTools";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
test("only administrators can edit the platform tool source", async () => {
  vi.mocked(api).mockResolvedValue({
    can_manage: false,
    configured: false,
    machines: [],
    source: {
      machine_id: "",
      directory: "/source",
      image: "registry/dtt:latest",
      allow_cached: false,
      revision: 0,
    },
  });
  render(<ToolPackagesPage />);
  await screen.findByText(/请管理员保存平台工具来源。/);
  expect(screen.queryByRole("button", { name: "保存工具来源" })).toBeNull();
});
test("machine tools retain results and start an explicit check", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/tool-packages") return { items: [] };
    if (method === "POST") return { id: "job", state: "running" };
    return [
      {
        id: "old",
        state: "success",
        phase: "完成",
        progress: 100,
        log: "done",
        result: {
          items: [{ tool: "dtt", status: "missing", path: null, details: "" }],
        },
      },
    ];
  });
  render(<MachineTools machineId="node" canManage={true} />);
  await screen.findByText("未安装");
  fireEvent.click(screen.getByRole("button", { name: "检查工具" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/machines/node/tool-jobs", "POST", {
      action: "check",
    }),
  );
});
test("read-only users cannot start remote jobs", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/tool-packages" ? { items: [] } : [],
  );
  render(<MachineTools machineId="node" canManage={false} />);
  await screen.findByText("尚未检查工具");
  expect(screen.queryByRole("button", { name: "检查工具" })).toBeNull();
});

test("one click deployment does not require a registered package", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "POST")
      return { id: "auto", state: "running", phase: "拉取镜像" };
    if (path === "/tool-packages") return { items: [] };
    return [];
  });
  render(<MachineTools machineId="node" canManage={true} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "一键部署 / 更新" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/machines/node/tool-jobs", "POST", {
      action: "auto_install",
      tool: "dtt",
    }),
  );
});

test("deployment shows popup while submitting and exposes failure outside logs", async () => {
  let finish!: (value: unknown) => void;
  const failed = {
    id: "deploy",
    action: "auto_install",
    state: "failed",
    phase: "失败",
    log: "Cannot connect to the Docker daemon",
    error_message: "Cannot connect to the Docker daemon",
  };
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : [],
  );
  render(<MachineTools machineId="node" canManage={true} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "一键部署 / 更新" }),
  );
  expect(
    await screen.findByRole("status", { name: "工具执行中" }),
  ).toBeTruthy();
  finish(failed);
  expect(await screen.findByText("部署失败")).toBeTruthy();
  expect(screen.queryByRole("status", { name: "工具执行中" })).toBeNull();
  expect(screen.getByRole("alert").textContent).toContain(
    "Cannot connect to the Docker daemon",
  );
});

test("a successful check does not hide the last failed deployment", async () => {
  vi.mocked(api).mockResolvedValue([
    { id: "check", action: "check", state: "success", phase: "完成", log: "" },
    {
      id: "deploy",
      action: "auto_install",
      state: "failed",
      phase: "失败",
      log: "Docker daemon unavailable",
    },
  ]);
  render(<MachineTools machineId="node" canManage={true} />);
  expect(await screen.findByText("检查完成")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain(
    "Docker daemon unavailable",
  );
  expect(screen.queryByText("部署成功")).toBeNull();
});

test("running deployment remains visible until polling confirms success", async () => {
  let state = "running";
  let started = false;
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method === "POST") started = true;
    const job = {
      id: "auto",
      action: "auto_install",
      state,
      phase: "拉取镜像",
      progress: 40,
      log: "pull",
    };
    return method === "POST" ? job : started ? [job] : [];
  });
  render(<MachineTools machineId="node" canManage={true} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "一键部署 / 更新" }),
  );
  await screen.findByText("拉取镜像", { selector: "strong" });
  expect(
    screen
      .getByRole("progressbar", { name: "工具任务进度" })
      .getAttribute("value"),
  ).toBe("40");
  state = "success";
  await waitFor(() => expect(screen.getByText("部署成功")).toBeTruthy(), {
    timeout: 3000,
  });
  expect(screen.queryByRole("status", { name: "工具执行中" })).toBeNull();
});
