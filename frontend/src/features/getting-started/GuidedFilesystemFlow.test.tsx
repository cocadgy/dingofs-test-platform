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
  fireEvent.click(screen.getByRole("combobox", { name: "存储配置" }));
  fireEvent.click(screen.getByRole("option", { name: "s3-prod · S3" }));
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
  expect(onNavigate).toHaveBeenCalledWith("#/start/filesystem/storage");
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
  fireEvent.click(screen.getByRole("combobox", { name: "存储配置" }));
  fireEvent.click(screen.getByRole("option", { name: "s3-prod · S3" }));
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


test("storage details appear only for the hovered item after opening the dropdown", async () => {
  const rados = { id: "storage-2", name: "ceph-prod", storage_type: "rados", revision: 1, enabled: true, has_secrets: true, parameters: { rados_mon: "10.0.0.2:6789", rados_poolname: "pool-a", rados_username: "client.admin", rados_clustername: "ceph", rados_key: "RADOS-SECRET" } };
  mockApi([{ ...profile, parameters: { ...profile.parameters, s3_sk: "S3-SECRET" } }, rados]);
  const onNavigate = vi.fn();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  const picker = screen.getByRole("combobox", { name: "存储配置" });
  fireEvent.mouseEnter(picker);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.click(picker);
  expect(screen.getByRole("listbox", { name: "存储配置列表" })).toBeInTheDocument();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.mouseEnter(screen.getByRole("option", { name: "s3-prod · S3" }));
  let details = screen.getByRole("tooltip");
  expect(details).toHaveTextContent("https://s3.example.com");
  expect(details).toHaveTextContent("bucket");
  expect(details).not.toHaveTextContent("10.0.0.2:6789");
  expect(details).not.toHaveTextContent("S3-SECRET");
  fireEvent.mouseEnter(screen.getByRole("option", { name: "ceph-prod · RADOS" }));
  details = screen.getByRole("tooltip");
  expect(details).toHaveTextContent("10.0.0.2:6789");
  expect(details).toHaveTextContent("client.admin");
  expect(details).not.toHaveTextContent("https://s3.example.com");
  expect(details).not.toHaveTextContent("RADOS-SECRET");
  fireEvent.click(screen.getByRole("option", { name: "ceph-prod · RADOS" }));
  expect(picker).toHaveTextContent("ceph-prod · RADOS");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "添加存储配置" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/filesystem/storage");
});


test("storage dropdown supports keyboard preview, selection and dismissal", async () => {
  const second = { ...profile, id: "storage-2", name: "s3-backup", parameters: { s3_endpoint: "https://backup.example.com", s3_bucketname: "backup" } };
  mockApi([profile, second]);
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  const picker = screen.getByRole("combobox", { name: "存储配置" });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  const first = screen.getByRole("option", { name: "s3-prod · S3" });
  await waitFor(() => expect(first).toHaveFocus());
  fireEvent.keyDown(first, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: "s3-backup · S3" })).toHaveFocus();
  expect(screen.getByRole("tooltip")).toHaveTextContent("https://backup.example.com");
  fireEvent.keyDown(screen.getByRole("option", { name: "s3-backup · S3" }), { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(picker).toHaveFocus();
  fireEvent.click(picker);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("returning from storage creation restores the filesystem draft and selected profile", async () => {
  mockApi();
  sessionStorage.setItem("guided-filesystem-draft", JSON.stringify({ clusterId: "cluster-1", fsName: "training-fs", suffix: "milliseconds", storageId: "storage-1", partition: "hash" }));
  sessionStorage.setItem("guided-filesystem-storage-return", "1");
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  expect(await screen.findByLabelText("文件系统名称")).toHaveValue("training-fs");
  expect(screen.getByLabelText("时间后缀")).toHaveValue("milliseconds");
  expect(screen.getByRole("combobox", { name: "存储配置" })).toHaveTextContent("s3-prod");
  expect(sessionStorage.getItem("guided-filesystem-storage-return")).toBeNull();
});

test("guided storage page uses the available desktop width", () => {
  const css = readFileSync("src/features/getting-started/getting-started.css", "utf8");
  expect(css).toMatch(/\.getting-started:has\(\.storage-profiles-page\)\s*\{[^}]*max-width:\s*1280px/);
});

test("timestamp suffix is frozen on confirmation and reused for submission", async () => {
  mockApi();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(screen.getByLabelText("文件系统名称"), { target: { value: "training" } });
  fireEvent.change(screen.getByLabelText("时间后缀"), { target: { value: "seconds" } });
  fireEvent.click(screen.getByRole("combobox", { name: "存储配置" }));
  fireEvent.click(screen.getByRole("option", { name: "s3-prod · S3" }));
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 10, 2, 18, 15, 30, 123));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText("training-20261102-181530")).toBeInTheDocument();
  vi.setSystemTime(new Date(2026, 10, 2, 18, 16, 45, 987));
  fireEvent.click(screen.getByRole("button", { name: "确认创建" }));
  vi.useRealTimers();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/clusters/cluster-1/resource-operations", "POST", expect.objectContaining({
    parameters: expect.objectContaining({ fs_name: "training-20261102-181530" }),
  })));

});
test("returning from confirmation regenerates the timestamp", async () => {
  mockApi();
  render(<GuidedFilesystemFlow admin userId="user-1" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("目标集群"), { target: { value: "cluster-1" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.change(screen.getByLabelText("文件系统名称"), { target: { value: "training" } });
  fireEvent.change(screen.getByLabelText("时间后缀"), { target: { value: "date" } });
  fireEvent.click(screen.getByRole("combobox", { name: "存储配置" }));
  fireEvent.click(screen.getByRole("option", { name: "s3-prod · S3" }));
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 10, 2, 18, 15, 30));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText("training-20261102")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
  vi.setSystemTime(new Date(2026, 10, 3, 8, 0, 0));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  vi.useRealTimers();
  expect(screen.getByText("training-20261103")).toBeInTheDocument();
});
