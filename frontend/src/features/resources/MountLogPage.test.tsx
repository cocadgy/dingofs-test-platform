import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { MountLogPage, mountLogRoute, mountLogUrl } from "./MountLogPage";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const cluster = "cluster-1", resource = "mount-1";
const record = { id: resource, kind: "mount", name: "/mnt/data", state: "unmounted", data: { mount_path: "/mnt/data", machine_id: "machine-1", target_user: "jenkins", fs_name: "data" } };
const files = [{ name: "client.ERROR", size: 20, mtime: 20 }, { name: "client.INFO", size: 10, mtime: 10 }];
function mockApi() {
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === `/clusters/${cluster}/resources`) return { resources: [record], machines: [{ id: "machine-1", name: "host-1", address: "10.0.0.1" }] } as never;
    if (path === `/clusters/${cluster}`) return { external_name: "test-cluster", revision: 1 } as never;
    if (method === "POST") return { id: "op-1", state: "pending" } as never;
    if (path === "/resource-operations/op-1") return { id: "op-1", state: "succeeded", result: { steps: [{ returncode: 0, data: (body as {filename?: string} | undefined)?.filename ? { text: "some log" } : { files } }] } } as never;
    throw new Error(path);
  });
}
test("mount log route is distinct from cluster service logs", () => {
  expect(mountLogRoute(mountLogUrl(cluster, resource))).toEqual({ clusterId: cluster, resourceId: resource });
  expect(mountLogRoute(mountLogUrl(cluster, resource, "client.INFO"))).toEqual({ clusterId: cluster, resourceId: resource, fileName: "client.INFO" });
  expect(mountLogRoute(`#/clusters/${cluster}/logs/service-1`)).toBeUndefined();
});
test("client logs open a dedicated page, including for unmounted records", async () => {
  mockApi();
  render(<MountLogPage clusterId={cluster} resourceId={resource} />);
  expect(screen.getByRole("status", { name: "正在读取客户端日志…" }).querySelector(".badou--animated")).toBeTruthy();
  expect(await screen.findByRole("heading", { name: /客户端日志/ })).toBeInTheDocument();
  const table = await screen.findByRole("table", { name: "日志文件列表" });
  await waitFor(() => expect(within(table).getByText("client.INFO")).toBeInTheDocument());
  expect(screen.getAllByText("/mnt/data").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "名称" }));
  expect(within(table).getByRole("columnheader", { name: /名称/ })).toHaveAttribute("aria-sort", "ascending");
  await waitFor(() => expect(api).toHaveBeenCalledWith(`/clusters/${cluster}/resource-operations`, "POST", expect.objectContaining({ action: "mount.logs", parameters: { resource_id: resource } })));
});

test("file URL is verified against fresh listing before reading content", async () => {
  let filename = "";
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === `/clusters/${cluster}/resources`) return { resources: [record], machines: [] } as never;
    if (path === `/clusters/${cluster}`) return { external_name: "test-cluster", revision: 1 } as never;
    if (method === "POST") {
      filename = String((body as { parameters: { filename?: string } }).parameters.filename || "");
      return { id: "op-1", state: "pending" } as never;
    }
    return { id: "op-1", state: "succeeded", result: { steps: [{ returncode: 0, data: filename ? { text: "line one\nline two", truncated: false } : { files } }] } } as never;
  });
  render(<MountLogPage clusterId={cluster} resourceId={resource} fileName="client.INFO" />);
  expect(await screen.findByRole("heading", { name: "client.INFO" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("日志内容")).toHaveTextContent("line two"));
  const requests = vi.mocked(api).mock.calls.filter(call => call[1] === "POST");
  expect((requests[0][2] as { parameters: { filename?: string } }).parameters.filename).toBeUndefined();
  expect((requests[1][2] as { parameters: { filename?: string } }).parameters.filename).toBe("client.INFO");
});

test("unknown URL filename is never sent to remote log reader", async () => {
  mockApi();
  render(<MountLogPage clusterId={cluster} resourceId={resource} fileName="../outside" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("未找到日志文件");
  const requests = vi.mocked(api).mock.calls.filter(call => call[1] === "POST");
  expect(requests).toHaveLength(1);
  expect((requests[0][2] as { parameters: { filename?: string } }).parameters.filename).toBeUndefined();
});

test("HTTP fallback sends a complete UUID request ID", async () => {
  const randomUUID = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
  try {
    mockApi();
    render(<MountLogPage clusterId={cluster} resourceId={resource} />);
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[1] === "POST")).toBe(true));
    const post = vi.mocked(api).mock.calls.find(call => call[1] === "POST")!;
    expect((post[2] as { request_id: string }).request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  } finally {
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: randomUUID });
  }
});

test("client search result route is distinct from raw file view", () => {
  expect(mountLogRoute(`#/clusters/${cluster}/resources/mounts/${resource}/logs?search=ERROR&match=client.INFO`)).toEqual({
    clusterId: cluster, resourceId: resource, searchKeyword: "ERROR", searchFile: "client.INFO", searchCaseSensitive: false,
  });
});
