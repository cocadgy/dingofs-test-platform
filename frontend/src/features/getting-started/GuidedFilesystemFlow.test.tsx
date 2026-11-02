// @ts-expect-error Node types are not part of the browser build.
import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GuidedFilesystemFlow } from "./GuidedFilesystemFlow";
import { GettingStartedPage } from "./GettingStartedPage";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
const cluster = { id: "cluster-1", external_name: "prod", machine_name: "node-1", machine_address: "10.0.0.1", os_user: "dingofs", revision: 4, creator_id: "user-1", archived: false, binding_state: "verified" };
const profile = { id: "storage-1", name: "s3-prod", storage_type: "s3", revision: 3, enabled: true, has_secrets: true, parameters: { s3_endpoint: "https://s3.example.com", s3_bucketname: "bucket" } };
afterEach(() => { cleanup(); sessionStorage.clear(); vi.mocked(api).mockReset(); });

function mockApi(profiles: unknown[] = [profile]) {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path.startsWith("/clusters/overview?")) return { items: [cluster], total: 1 };
    if (path === "/storage-profiles") return profiles;
    if (path === "/clusters/cluster-1/resources") return { catalog: [{ action: "fs.create", label: "创建文件系统", mutating: true, fields: [] }], operations: [] };
    if (path === "/clusters/cluster-1/resource-operations" && method === "POST") return { id: "op-1", action: "fs.create", state: "succeeded" };
    throw new Error(`Unexpected API: ${method} ${path}`);
  });
}

test("wizard confirms name, stored credentials and partition before one create request", async () => {
  mockApi();
  const onNavigate = vi.fn();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(await screen.findByLabelText("文件系统名称"), { target: { value: "training-fs" } });
  fireEvent.change(screen.getByLabelText("存储配置"), { target: { value: "storage-1" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText("training-fs")).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([path, method]) => path === "/clusters/cluster-1/resource-operations" && method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "确认创建" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/cluster-1/resource-operations", "POST", expect.objectContaining({
    base_revision: 4, action: "fs.create", confirmed: true,
    parameters: { fs_name: "training-fs", partition_type: "hash", storage_profile_id: "storage-1", storage_profile_revision: 3 },
  })));
  fireEvent.click(await screen.findByRole("button", { name: "查看文件系统" }));
  expect(onNavigate).toHaveBeenCalledWith("#/clusters/cluster-1/resources");
});

test("missing usable storage profile directs user to configuration without submitting", async () => {
  mockApi([{ ...profile, has_secrets: false }]);
  const onNavigate = vi.fn();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "添加存储配置" }));
  expect(onNavigate).toHaveBeenCalledWith("#/storage");
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith("/resource-operations"))).toBe(false);
});


test("start chooser opens filesystem wizard", () => {
  const onNavigate = vi.fn();
  render(<GettingStartedPage route="chooser" onNavigate={onNavigate} onDirty={vi.fn()} admin />);
  fireEvent.change(screen.getByLabelText("想做什么"), { target: { value: "filesystem" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/filesystem");
});


test("no cluster starts cluster onboarding and returns to filesystem creation", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith("/clusters/overview?")) return { items: [], total: 0 };
    if (path === "/storage-profiles") return [];
    throw new Error(`Unexpected API: ${path}`);
  });
  const onNavigate = vi.fn();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "先添加集群" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/cluster");
  expect(sessionStorage.getItem("guided-filesystem-return")).toBe("1");
});


test("create submission cannot be sent twice while the first request is unresolved", async () => {
  let resolvePost!: (value: unknown) => void;
  mockApi();
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, body, options) => {
    if (path === "/clusters/cluster-1/resource-operations" && method === "POST") return new Promise((resolve) => { resolvePost = resolve; });
    return base(path, method, body, options);
  });
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(screen.getByLabelText("文件系统名称"), { target: { value: "training-fs" } });
  fireEvent.change(screen.getByLabelText("存储配置"), { target: { value: "storage-1" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "确认创建" }));
  expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
  expect(vi.mocked(api).mock.calls.filter(([path, method]) => path === "/clusters/cluster-1/resource-operations" && method === "POST")).toHaveLength(1);
  resolvePost({ id: "op-1", action: "fs.create", state: "succeeded" });
  expect(await screen.findByRole("button", { name: "查看文件系统" })).toBeInTheDocument();
});


test("cluster options identify the management machine and operating-system user", async () => {
  mockApi();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  expect(await screen.findByRole("option", { name: "prod · node-1 (10.0.0.1) · dingofs" })).toHaveValue("cluster-1");
});


test("advanced-options panel has horizontal breathing room", () => {
  const css = readFileSync("src/features/getting-started/getting-started.css", "utf8");
  expect(css).toMatch(/\.guided-filesystem-flow details\s*\{[^}]*padding:\s*16px/);
});


test("storage picker previews available profiles on hover without exposing secrets", async () => {
  const rados = { id: "storage-2", name: "ceph-prod", storage_type: "rados", revision: 1, enabled: true, has_secrets: true, parameters: { rados_mon: "10.0.0.2:6789", rados_poolname: "pool-a", rados_username: "client.admin", rados_clustername: "ceph", rados_key: "RADOS-SECRET" } };
  mockApi([{ ...profile, parameters: { ...profile.parameters, s3_sk: "S3-SECRET" } }, rados]);
  const onNavigate = vi.fn();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  const picker = screen.getByLabelText("存储配置");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.mouseEnter(picker);
  const details = screen.getByRole("tooltip");
  expect(details).toHaveTextContent("https://s3.example.com");
  expect(details).toHaveTextContent("bucket");
  expect(details).toHaveTextContent("10.0.0.2:6789");
  expect(details).toHaveTextContent("client.admin");
  expect(details).not.toHaveTextContent("S3-SECRET");
  expect(details).not.toHaveTextContent("RADOS-SECRET");
  fireEvent.mouseLeave(picker);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "添加存储配置" }));
  expect(onNavigate).toHaveBeenCalledWith("#/storage");
});
