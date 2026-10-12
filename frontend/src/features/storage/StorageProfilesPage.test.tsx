import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StorageProfilesPage } from "./StorageProfilesPage";

const profile = {
  id: "storage-1",
  name: "共享对象存储",
  storage_type: "s3",
  description: "测试文件系统使用",
  enabled: true,
  revision: 4,
  creator_id: "user-1",
  can_manage: true,
  parameters: {
    s3_endpoint: "https://s3.example.test",
    s3_bucketname: "test-data",
  },
  has_secrets: true,
  created_at: "2026-10-08T01:00:00Z",
  updated_at: "2026-10-08T02:00:00Z",
};
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
afterEach(() => vi.unstubAllGlobals());

it("lists shared profiles and only offers management for permitted records", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json([
        profile,
        {
          ...profile,
          id: "storage-2",
          name: "其他成员的 RADOS",
          storage_type: "rados",
          can_manage: false,
          enabled: false,
          parameters: {
            rados_poolname: "ceph-test",
            rados_mon: "ceph.example.test:6789",
            rados_username: "client.test",
            rados_clustername: "ceph",
          },
        },
      ]),
    ),
  );
  render(<StorageProfilesPage onDirty={vi.fn()} />);
  const editable = (await screen.findByText("共享对象存储")).closest("tr")!;
  const shared = screen.getByText("其他成员的 RADOS").closest("tr")!;
  expect(within(editable).getByRole("button", { name: "编辑" })).toBeEnabled();
  expect(within(shared).queryByRole("button")).toBeNull();
  expect(within(shared).getByText("ceph-test")).toBeInTheDocument();
  expect(within(shared).getByText("已禁用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "新建存储配置" })).toBeEnabled();
});

it("creates S3 profiles with typed parameters and tracks unsaved changes", async () => {
  const requests: { method: string; body: any }[] = [];
  const dirty = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({
        method: init?.method || "GET",
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return json(init?.method === "POST" ? profile : []);
    }),
  );
  render(<StorageProfilesPage onDirty={dirty} />);
  fireEvent.click(screen.getByRole("button", { name: "新建存储配置" }));
  change("配置名称", "测试 S3");
  change("Endpoint", "https://s3.example.test");
  change("Bucket", "test-data");
  change("Access Key", "example-ak");
  change("Secret Key", "example-sk");
  expect(screen.getByLabelText("Access Key")).toHaveAttribute(
    "type",
    "password",
  );
  expect(screen.getByLabelText("Secret Key")).toHaveAttribute(
    "type",
    "password",
  );
  expect(dirty).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button", { name: "创建配置" }));
  await screen.findByText("存储配置已创建");
  expect(requests.find((request) => request.method === "POST")?.body).toEqual({
    name: "测试 S3",
    storage_type: "s3",
    description: "",
    enabled: true,
    parameters: {
      s3_endpoint: "https://s3.example.test",
      s3_bucketname: "test-data",
      s3_ak: "example-ak",
      s3_sk: "example-sk",
    },
  });
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(screen.queryByLabelText("Secret Key")).toBeNull();
});

it("retains an edited draft after conflict and omits unchanged credentials", async () => {
  const requests: { method: string; body: any }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({
        method: init?.method || "GET",
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return init?.method === "PUT"
        ? json({ message: "配置已被修改，请重新读取" }, 409)
        : json([profile]);
    }),
  );
  const dirty = vi.fn();
  render(<StorageProfilesPage onDirty={dirty} />);
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  expect(screen.getByLabelText("存储类型")).toBeDisabled();
  expect(screen.getByLabelText("Access Key")).toHaveValue("");
  expect(screen.getByLabelText("Secret Key")).toHaveValue("");
  expect(dirty).toHaveBeenLastCalledWith(false);
  change("配置名称", "保留这个草稿");
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("配置名称")).toHaveValue("保留这个草稿");
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(requests.find((request) => request.method === "PUT")?.body).toEqual({
    name: "保留这个草稿",
    storage_type: "s3",
    description: "测试文件系统使用",
    enabled: true,
    revision: 4,
    parameters: {
      s3_endpoint: "https://s3.example.test",
      s3_bucketname: "test-data",
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() =>
    expect(requests.filter((request) => request.method === "GET")).toHaveLength(
      2,
    ),
  );
  expect(screen.getByLabelText("配置名称")).toHaveValue("保留这个草稿");
});

it("creates RADOS profiles without leftover S3 parameters", async () => {
  const requests: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body) requests.push(JSON.parse(init.body as string));
      return json(
        init?.method === "POST" ? { ...profile, storage_type: "rados" } : [],
      );
    }),
  );
  render(<StorageProfilesPage onDirty={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "新建存储配置" }));
  change("Access Key", "discarded-s3-value");
  change("存储类型", "rados");
  change("配置名称", "测试 RADOS");
  change("Username", "client.test");
  change("Key", "example-rados-key");
  change("Monitors", "ceph.example.test:6789");
  change("Pool", "ceph-test");
  change("Cluster Name", "ceph");
  fireEvent.click(screen.getByLabelText("启用此配置"));
  fireEvent.click(screen.getByRole("button", { name: "创建配置" }));
  await screen.findByText("存储配置已创建");
  expect(requests[0]).toEqual({
    name: "测试 RADOS",
    storage_type: "rados",
    description: "",
    enabled: false,
    parameters: {
      rados_username: "client.test",
      rados_key: "example-rados-key",
      rados_mon: "ceph.example.test:6789",
      rados_poolname: "ceph-test",
      rados_clustername: "ceph",
    },
  });
});

it("preserves credentials when disabling and requires confirmation to delete only the saved configuration", async () => {
  const requests: { url: string; method: string; body: any }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({
        url: String(url),
        method: init?.method || "GET",
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : json(init?.method === "PUT" ? profile : [profile]);
    }),
  );
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<StorageProfilesPage onDirty={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "禁用" }));
  await screen.findByText("存储配置已禁用");
  expect(requests.find((request) => request.method === "PUT")?.body).toEqual({
    name: "共享对象存储",
    storage_type: "s3",
    description: "测试文件系统使用",
    enabled: false,
    revision: 4,
    parameters: {
      s3_endpoint: "https://s3.example.test",
      s3_bucketname: "test-data",
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  expect(confirm).toHaveBeenCalledWith(
    expect.stringMatching(/仅删除平台保存的配置.*不会删除.*文件系统/),
  );
  expect(
    requests.filter((request) => request.method === "DELETE"),
  ).toHaveLength(0);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  await screen.findByText("存储配置已删除");
  expect(requests.find((request) => request.method === "DELETE")?.url).toBe(
    "/api/v1/storage-profiles/storage-1?revision=4",
  );
});

it("allows retry after load failure and protects a dirty form on cancel", async () => {
  let loads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      ++loads === 1 ? json({ message: "暂时无法读取" }, 503) : json([profile]),
    ),
  );
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<StorageProfilesPage onDirty={vi.fn()} />);
  await screen.findByText("暂时无法读取");
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await screen.findByText("共享对象存储");
  expect(screen.queryByText("暂时无法读取")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "新建存储配置" }));
  change("配置名称", "未保存的配置");
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.getByLabelText("配置名称")).toHaveValue("未保存的配置");
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByLabelText("配置名称")).toBeNull();
});
