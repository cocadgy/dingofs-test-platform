import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
function setup(planState = "succeeded") {
  sessionStorage.setItem("guided-cache-draft-u", JSON.stringify({ ...blankCacheDraft(), clusterId: "c", name: "shared",
    rows: machines.map((machine, i) => ({ ...newCacheRow(machine), directory: "/cache", count: i + 1 })) }));
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.startsWith("/clusters/overview")) return { items: [cluster], total: 1 };
    if (path === "/clusters/c/resources") return { catalog: [{ action: "cache.plan" }], machines, resources: [], operations: [], cache_profiles: [] };
    if (path === "/clusters/c/resource-operations" && method === "POST") {
      const action = (body as {action: string}).action;
      return { id: action === "cache.plan" ? "plan-id" : "create-id", action, state: action === "cache.plan" ? planState : "succeeded" };
    }
    throw Error(path);
  });
  render(<GuidedCacheFlow admin userId="u" route="#/start/cache" onNavigate={vi.fn()} onDirty={vi.fn()} />);
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
test("explicit binary directory can be overridden per machine", () => {
  const draft = { ...blankCacheDraft(), source: "path" as const, binaryDirectory: "/opt/cache",
    rows: machines.map((machine, i) => ({ ...newCacheRow(machine), directory: "/cache", binaryDirectory: i ? "/custom/bin" : "" })) };
  expect(cacheMembers(draft).map(row => row.binary_directory)).toEqual(["/opt/cache", "/custom/bin"]);
});

test("bulk GiB capacity survives confirmation and is submitted as MiB", async () => {
  setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByText("批量填写"));
  fireEvent.change(screen.getAllByLabelText("容量单位")[0], { target: { value: "GiB" } });
  fireEvent.change(screen.getAllByLabelText("每节点容量")[0], { target: { value: "1.5" } });
  fireEvent.click(screen.getByRole("button", { name: "应用到已选机器" }));
  expect(screen.getAllByLabelText("每节点容量")[1]).toHaveValue(1.5);
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getAllByText("1.5 GiB")).toHaveLength(2);
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
    action: "cache.plan", parameters: expect.objectContaining({ cache_options: { cache_expire_s: "90" } }),
  })));
});
