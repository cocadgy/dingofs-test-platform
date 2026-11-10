import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GuidedCacheFlow } from "./GuidedCacheFlow";
import { blankCacheDraft, cacheMembers, newCacheRow } from "./guidedCacheModel";
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
const machines = [
  { id: "m1", name: "node-1", address: "10.0.0.1", ssh_user: "dingofs", can_manage: true },
  { id: "m2", name: "node-2", address: "10.0.0.2", ssh_user: "dingofs", can_manage: true },
];
const cluster = { id: "c", external_name: "prod", machine_name: "control", machine_address: "10.0.0.3", os_user: "dingofs", creator_id: "u", revision: 1, binding_state: "verified" };
afterEach(() => { cleanup(); sessionStorage.clear(); vi.mocked(api).mockReset(); });
function setup(planState = "succeeded", createState = "succeeded") {
  const onDirty = vi.fn();
  sessionStorage.setItem("guided-cache-draft-u", JSON.stringify({ ...blankCacheDraft(), clusterId: "c", name: "shared",
    rows: machines.map((machine, i) => ({ ...newCacheRow(machine), directory: "/cache", count: i + 1 })) }));
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.startsWith("/clusters/overview")) return { items: [cluster], total: 1 };
    if (path === "/clusters/c/resources") return { catalog: [{ action: "cache.plan" }], machines, resources: [], operations: [], cache_profiles: [] };
    if (path === "/clusters/c/resource-operations" && method === "POST") {
      const action = (body as {action: string}).action;
      return { id: action === "cache.plan" ? "plan-id" : "create-id", action, state: action === "cache.plan" ? planState : createState };
    }
    throw Error(path);
  });
  render(<GuidedCacheFlow admin userId="u" route="#/start/cache" onNavigate={vi.fn()} onDirty={onDirty} />);
  return onDirty;
}
async function confirm() {
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText(/2 台机器，共 3 个缓存节点/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "检查并创建缓存组" }));
}
test("all selected machines join one group after preparation succeeds", async () => {
  setup(); await confirm();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/c/resource-operations", "POST", expect.objectContaining({ action: "cache.create", parameters: { plan_id: "plan-id" }, request_id: "plan-id" })));
  const request = vi.mocked(api).mock.calls.find(([, ,body]) => (body as {action?:string})?.action === "cache.plan")![2] as {parameters:{group_name:string;members:{machine_id:string;binary_source:string}[]}};
  expect(request.parameters.group_name).toBe("shared");
  expect(request.parameters.members.map(row => row.machine_id)).toEqual(["m1", "m2", "m2"]);
  expect(request.parameters.members.every(row => row.binary_source === "default")).toBe(true);
});
test("failed preparation never starts any cache nodes", async () => {
  setup("failed"); await confirm();
  expect(await screen.findByRole("button", { name: "返回修改并重新检查" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([, ,body]) => (body as {action?:string})?.action === "cache.create")).toBe(false);
});
test("completed cache creation clears the unsaved-draft navigation guard", async () => {
  const onDirty = setup();
  await confirm();
  await screen.findByRole("heading", { name: "缓存组创建完成" });
  await waitFor(() => expect(onDirty).toHaveBeenLastCalledWith(false));
});
test("failed preparation keeps the unsaved-draft navigation guard", async () => {
  const onDirty = setup("failed");
  await confirm();
  await screen.findByRole("button", { name: "返回修改并重新检查" });
  expect(onDirty).toHaveBeenLastCalledWith(true);
});
test("successful cache planning does not clear the guard when creation fails", async () => {
  const onDirty = setup("succeeded", "failed");
  await confirm();
  await screen.findByRole("button", { name: "重试失败及未完成节点" });
  expect(onDirty).toHaveBeenLastCalledWith(true);
});
test("explicit binary directory can be overridden per machine", () => {
  const draft = { ...blankCacheDraft(), source: "path" as const, binaryDirectory: "/opt/cache",
    rows: machines.map((machine, i) => ({ ...newCacheRow(machine), directory: "/cache", binaryDirectory: i ? "/custom/bin" : "" })) };
  expect(cacheMembers(draft).map(row => row.binary_directory)).toEqual(["/opt/cache", "/custom/bin"]);
});

test("per-machine GiB capacity stays independent and is submitted as MiB", async () => {
  setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(screen.getAllByLabelText("容量单位")[0], { target: { value: "GiB" } });
  fireEvent.change(screen.getAllByLabelText("每节点容量")[0], { target: { value: "1.5" } });
  expect(screen.getAllByLabelText("每节点容量")[1]).toHaveValue(1024);
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getAllByText("1.5 GiB")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "检查并创建缓存组" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/c/resource-operations", "POST", expect.objectContaining({
    action: "cache.plan", parameters: expect.objectContaining({ members: expect.arrayContaining([expect.objectContaining({ cache_size_mb: 1536 })]) }),
  })));
});
test("edited options persist in draft and reach cache planning request", async () => {
  setup();
  const saved = JSON.parse(sessionStorage.getItem("guided-cache-draft-u")!);
  saved.options = { cache_expire_s: "90" };
  cleanup(); sessionStorage.setItem("guided-cache-draft-u", JSON.stringify(saved));
  render(<GuidedCacheFlow admin userId="u" route="#/start/cache" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await confirm();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/c/resource-operations", "POST", expect.objectContaining({
    action: "cache.plan", parameters: expect.objectContaining({ members: expect.arrayContaining([expect.objectContaining({ cache_options: { cache_expire_s: "90" } })]) }),
  })));
});

test("an enabled stale RDMA pair cannot advance to confirmation", async () => {
  setup();
  const saved = JSON.parse(sessionStorage.getItem("guided-cache-draft-u")!);
  saved.rows[0] = { ...saved.rows[0], rdma: true, rdmaDevice: "stale-device", rdmaPort: 1 };
  cleanup(); sessionStorage.setItem("guided-cache-draft-u", JSON.stringify(saved));
  render(<GuidedCacheFlow admin userId="u" route="#/start/cache" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.queryByRole("button", { name: "检查并创建缓存组" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("alert").some(item => item.textContent?.includes("不属于当前机器"))).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([, method]) => method === "POST")).toBe(false);
});

test("each machine has its own weight and all its nodes inherit it", async () => {
  setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.queryByLabelText(/一致性哈希权重/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  const weights = screen.getAllByLabelText(/一致性哈希权重/);
  expect(weights).toHaveLength(2);
  fireEvent.change(weights[0], { target: { value: "50" } });
  fireEvent.change(weights[1], { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("columnheader", { name: "一致性哈希权重" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "50" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "200" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "检查并创建缓存组" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/c/resource-operations", "POST", expect.objectContaining({ action: "cache.plan" })));
  const request = vi.mocked(api).mock.calls.find(([, , body]) => (body as {action?:string})?.action === "cache.plan")![2] as {parameters:{members:{group_weight:number}[]}};
  expect(request.parameters.members.map(m => m.group_weight)).toEqual([50, 200, 200]);
});

test("path source is global but directories belong to machines; adding clones current settings only", async () => {
  setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(screen.getByLabelText("程序来源"), { target: { value: "path" } });
  expect(screen.queryByLabelText("程序所在目录")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getAllByLabelText("node-2 · 10.0.0.2")[0]);
  fireEvent.change(screen.getByLabelText(/一致性哈希权重/), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText(/程序所在目录/), { target: { value: "/a/bin" } });
  fireEvent.click(screen.getByLabelText("node-2 · 10.0.0.2"));
  expect(screen.getAllByLabelText(/一致性哈希权重/)[1]).toHaveValue(60);
  expect(screen.getAllByLabelText(/程序所在目录/)[1]).toHaveValue("");
  fireEvent.change(screen.getAllByLabelText(/一致性哈希权重/)[0], { target: { value: "90" } });
  expect(screen.getAllByLabelText(/一致性哈希权重/)[1]).toHaveValue(60);
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.queryByRole("button", { name: "检查并创建缓存组" })).not.toBeInTheDocument();
  fireEvent.change(screen.getAllByLabelText(/程序所在目录/)[1], { target: { value: "/b/bin" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "检查并创建缓存组" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/c/resource-operations", "POST", expect.objectContaining({
    action: "cache.plan", parameters: expect.objectContaining({ members: expect.arrayContaining([
      expect.objectContaining({ machine_id: "m1", binary_directory: "/a/bin", group_weight: 90 }),
      expect.objectContaining({ machine_id: "m2", binary_directory: "/b/bin", group_weight: 60 }),
    ]) }),
  })));
});
test("copying settings requires explicit target selection and overwrite confirmation", async () => {
  setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  const cards = screen.getAllByRole("group");
  const first = within(cards[0]);
  fireEvent.change(first.getByLabelText(/一致性哈希权重/), { target: { value: "60" } });
  fireEvent.click(first.getByText("复制缓存参数到其他机器"));
  fireEvent.click(first.getByLabelText("node-2 · 10.0.0.2"));
  fireEvent.click(first.getByRole("button", { name: "复制参数" }));
  expect(screen.getAllByLabelText(/一致性哈希权重/)[1]).toHaveValue(100);
  fireEvent.click(first.getByRole("button", { name: "确认覆盖" }));
  expect(screen.getAllByLabelText(/一致性哈希权重/)[1]).toHaveValue(60);
  expect(screen.getAllByLabelText("节点数量")[1]).toHaveValue(2);
});
