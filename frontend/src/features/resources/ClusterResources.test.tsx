import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterResources } from "./ClusterResources";
vi.mock("../../api/client", async (importOriginal) => ({ ...await importOriginal<typeof import("../../api/client")>(), api: vi.fn() }));
const catalog = [
  {
    action: "fs.list",
    label: "查询文件系统",
    section: "filesystem",
    mutating: false,
    fields: [],
  },
  {
    action: "fs.create",
    label: "创建文件系统",
    section: "filesystem",
    mutating: true,
    fields: [
      { key: "fs_name", label: "文件系统名称", type: "text", required: true },
      {
        key: "secret_key",
        label: "存储密钥",
        type: "password",
        required: true,
      },
    ],
  },
  {
    action: "cache.create",
    label: "创建缓存组",
    section: "cache",
    mutating: true,
    fields: [
      { key: "group_name", label: "缓存组名称", type: "text", required: true },
      { key: "members", label: "缓存成员", type: "members", required: true },
    ],
  },
  {
    action: "cache.stop",
    label: "停止缓存组",
    section: "cache",
    mutating: true,
    fields: [
      { key: "resource_id", label: "缓存组", type: "text", required: true },
    ],
  },
  {
    action: "cache.delete",
    label: "删除缓存组",
    section: "cache",
    mutating: true,
    fields: [
      { key: "resource_id", label: "缓存组", type: "text", required: true },
    ],
  },
  {
    action: "mount.create",
    label: "挂载文件系统",
    section: "mount",
    mutating: true,
    fields: [
      { key: "machine_id", label: "挂载机器", type: "text", required: true },
      { key: "target_user", label: "执行用户", type: "text", required: true },
      {
        key: "fs_name",
        label: "挂载文件系统名称",
        type: "text",
        required: true,
      },
      { key: "mount_path", label: "挂载路径", type: "text", required: true },
      { key: "subdir", label: "子目录", type: "text", default: "/" },
      { key: "use_rdma", label: "使用 RDMA", type: "boolean", default: false },
    ],
  },
  {
    action: "mount.status",
    label: "查看挂载状态",
    section: "mount",
    mutating: false,
    fields: [
      { key: "resource_id", label: "挂载记录", type: "text", required: true },
    ],
  },
  {
    action: "mount.unmount",
    label: "卸载文件系统",
    section: "mount",
    mutating: true,
    fields: [
      { key: "resource_id", label: "挂载记录", type: "text", required: true },
    ],
  },
  {
    action: "mount.logs",
    label: "客户端日志",
    section: "mount",
    mutating: false,
    fields: [
      { key: "resource_id", label: "挂载记录", type: "text", required: true },
      { key: "filename", label: "日志文件名", type: "text" },
      {
        key: "lines",
        label: "日志行数",
        type: "select",
        options: ["100", "500", "1000"],
        default: "100",
      },
    ],
  },
];
const snapshot = {
  storage_profiles: [
    {
      id: "storage-1",
      name: "测试 S3",
      storage_type: "s3",
      enabled: true,
      revision: 2,
      can_manage: true,
      has_secrets: true,
      parameters: { s3_endpoint: "http://s3.test", s3_bucketname: "bucket" },
    },
  ],
  catalog,
  machines: [
    {
      id: "m1",
      name: "node-one",
      address: "10.0.0.1",
      ssh_user: "jenkins",
      can_manage: true,
    },
    {
      id: "m2",
      name: "private-node",
      address: "10.0.0.2",
      ssh_user: "root",
      can_manage: false,
    },
  ],
  resources: [
    {
      id: "cache1",
      kind: "cache",
      name: "fast-cache",
      state: "running",
      data: { members: [{ machine_id: "m1" }] },
      created_at: "2026-01-01",
    },
    {
      id: "mount1",
      kind: "mount",
      name: "data-mount",
      state: "mounted",
      data: { fs_name: "data", mount_path: "/mnt/data", machine_id: "m1" },
      created_at: "2026-01-01",
    },
  ],
  operations: [],
};
const props = { id: "c1", name: "real-cluster", revision: 4, canManage: true };
const done = {
  id: "op1",
  action: "fs.list",
  state: "succeeded",
  payload: {},
  result: { steps: [{ stdout: "done", stderr: "", returncode: 0 }] },
};
beforeEach(() => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/resources") ? snapshot : done,
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(api).mockReset();
});
async function section(name: string) {
  const nav = await screen.findByRole("navigation", { name: "资源功能" });
  const label =
    name === "挂载与客户端日志"
      ? "挂载点"
      : name === "资源操作记录"
        ? "操作记录"
        : name;
  fireEvent.click(within(nav).getByRole("button", { name: new RegExp(label) }));
  return within(await screen.findByRole("region", { name }));
}
async function choose(sectionName: string, action: string) {
  const ui = await section(sectionName);
  const label =
    action === "quota.dir.set"
      ? "设置目录配额"
      : catalog.find((item) => item.action === action)!.label;
  if (action.startsWith("quota.dir."))
    fireEvent.click(ui.getByRole("button", { name: "目录配额" }));
  fireEvent.click(ui.getByRole("button", { name: label }));
  return ui;
}
// Most tests assert explicit operations; module-entry query is covered separately.
const posts = () => {
  let skippedEntry = false;
  return vi.mocked(api).mock.calls.filter((call) => {
    if (call[1] !== "POST") return false;
    if (
      !skippedEntry &&
      (call[2] as { action?: string })?.action === "fs.list"
    ) {
      skippedEntry = true;
      return false;
    }
    return true;
  });
};
function mockResponse(value: typeof snapshot | Record<string, unknown>) {
  vi.mocked(api).mockImplementation(async (_path, method, payload) => {
    if (
      method === "POST" &&
      (payload as { action?: string })?.action === "fs.list" &&
      "catalog" in value
    ) {
      const operations = (value.operations || []) as (typeof done)[];
      return operations.find((item) => item.action === "fs.list") || done;
    }
    return value;
  });
}

test("read-only viewers can inspect saved resources and failures but cannot issue any remote action", async () => {
  mockResponse({
    ...snapshot,
    operations: [
      {
        ...done,
        state: "interrupted",
        error_code: "CONNECTION_LOST",
        message: "结果待核实",
        result: {
          steps: [
            { stdout: "created one", stderr: "second failed", returncode: 1 },
          ],
        },
      },
    ],
  });
  render(<ClusterResources {...props} canManage={false} />);
  expect(await screen.findByText("fast-cache")).toBeInTheDocument();
  expect(screen.getByText("data-mount")).toBeInTheDocument();
  expect(screen.getByText(/CONNECTION_LOST/)).toBeInTheDocument();
  expect(screen.getByText("second failed")).toBeInTheDocument();
  const ui = await section("文件系统");
  expect(ui.getByRole("button", { name: "刷新文件系统列表" })).toBeDisabled();
  expect(ui.getByRole("button", { name: "创建文件系统" })).toBeDisabled();
  expect(posts()).toHaveLength(0);
});

test("mutation confirmation identifies the real cluster and target, and cancelling sends no command", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ClusterResources {...props} />);
  const ui = await choose("文件系统", "fs.create");
  fireEvent.change(ui.getByLabelText("文件系统名称"), {
    target: { value: "finance" },
  });
  fireEvent.change(ui.getByLabelText("存储配置"), {
    target: { value: "storage-1" },
  });
  fireEvent.click(ui.getByRole("button", { name: "执行创建文件系统" }));
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("real-cluster"),
  );
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("finance"),
  );
  expect(window.confirm).not.toHaveBeenCalledWith(
    expect.stringContaining("secret-value"),
  );
  expect(posts()).toHaveLength(0);
});

test("confirmed creation submits once with revision and unique request ID, and references storage without sending credentials", async () => {
  render(<ClusterResources {...props} />);
  const ui = await choose("文件系统", "fs.create");
  fireEvent.change(ui.getByLabelText("文件系统名称"), {
    target: { value: "finance" },
  });
  fireEvent.change(ui.getByLabelText("存储配置"), {
    target: { value: "storage-1" },
  });
  fireEvent.click(ui.getByRole("button", { name: "执行创建文件系统" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0]).toEqual([
    "/clusters/c1/resource-operations",
    "POST",
    {
      base_revision: 4,
      request_id: expect.any(String),
      action: "fs.create",
      parameters: {
        fs_name: "finance",
        partition_type: "hash",
        storage_profile_id: "storage-1",
        storage_profile_revision: 2,
      },
      confirmed: true,
    },
  ]);
  expect(ui.queryByLabelText("存储密钥")).toBeNull();
  expect(localStorage.length).toBe(0);
});

test("cache members use manageable machine choices and send structured member fields", async () => {
  render(<ClusterResources {...props} />);
  const ui = await section("缓存组");
  fireEvent.change(ui.getByLabelText("缓存组名称"), {
    target: { value: "hot-cache" },
  });
  expect(
    ui.queryByRole("option", { name: /private-node/ }),
  ).not.toBeInTheDocument();
  fireEvent.change(ui.getByLabelText("成员 1 机器"), {
    target: { value: "m1" },
  });
  fireEvent.change(ui.getByLabelText("成员 1 执行用户"), {
    target: { value: "dingofs" },
  });
  fireEvent.change(ui.getByLabelText("成员 1 监听 IP"), {
    target: { value: "10.0.0.1" },
  });
  fireEvent.change(ui.getByLabelText("成员 1 缓存目录"), {
    target: { value: "/srv/cache" },
  });
  fireEvent.click(ui.getByRole("button", { name: "添加缓存成员" }));
  expect(ui.getByLabelText("成员 2 机器")).toBeInTheDocument();
  fireEvent.click(ui.getByRole("button", { name: "移除成员 2" }));
  fireEvent.click(ui.getByRole("button", { name: "执行创建缓存组" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0][2]).toMatchObject({
    action: "cache.create",
    parameters: {
      group_name: "hot-cache",
      members: [
        expect.objectContaining({
          machine_id: "m1",
          target_user: "dingofs",
          listen_ip: "10.0.0.1",
          listen_port: expect.any(Number),
          cache_size_mb: expect.any(Number),
          cache_dir: "/srv/cache",
          use_rdma: false,
        }),
      ],
    },
  });
});

test("saved cache and mount actions address the saved resource ID", async () => {
  render(<ClusterResources {...props} />);
  const ui = await section("缓存组");
  fireEvent.click(ui.getByRole("button", { name: "停止 fast-cache" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0][2]).toMatchObject({
    action: "cache.stop",
    parameters: { resource_id: "cache1" },
    confirmed: true,
  });
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("fast-cache"),
  );
});

test("client log shortcut navigates to its dedicated page", async () => {
  window.location.hash = "#/clusters/c1/resources";
  render(<ClusterResources {...props} />);
  const ui = await section("挂载与客户端日志");
  fireEvent.click(ui.getByRole("button", { name: "日志 data-mount" }));
  expect(window.location.hash).toBe("#/clusters/c1/resources/mounts/mount1/logs");
  expect(posts()).toHaveLength(0);
});

test("sudo challenge authenticates against the resource operation and clears its password", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/resources")) return snapshot;
    if (path.endsWith("/authenticate")) return done;
    return {
      ...done,
      state: "needs_password",
      result: null,
      challenge: "nonce",
      auth_account: "jenkins",
      target_user: "dingofs",
      machine_name: "node-one",
    };
  });
  render(<ClusterResources {...props} />);
  const ui = await section("文件系统");
  // Entering the module starts the list operation automatically.
  const password = await screen.findByLabelText("认证密码");
  expect(
    screen.getByText("jenkins", { selector: "strong" }),
  ).toBeInTheDocument();
  fireEvent.change(password, { target: { value: "one-time-secret" } });
  fireEvent.click(screen.getByRole("button", { name: "验证并继续" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/resource-operations/op1/authenticate",
      "POST",
      { challenge: "nonce", password: "one-time-secret" },
    ),
  );
  expect(screen.queryByLabelText("认证密码")).not.toBeInTheDocument();
});

test("uncertain network outcomes stay visible and never silently repeat a mutation", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/resources")) return snapshot;
    throw new Error("连接中断");
  });
  render(<ClusterResources {...props} />);
  const ui = await section("缓存组");
  fireEvent.click(ui.getByRole("button", { name: "停止 fast-cache" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/核实/);
  expect(posts()).toHaveLength(1);
});

test("mount creation keeps the selected machine, user, path and catalog defaults", async () => {
  render(<ClusterResources {...props} />);
  const ui = await section("挂载与客户端日志");
  fireEvent.change(ui.getByLabelText("挂载机器"), { target: { value: "m1" } });
  fireEvent.change(ui.getByLabelText("执行用户"), {
    target: { value: "dingofs" },
  });
  fireEvent.change(ui.getByLabelText("挂载文件系统名称"), {
    target: { value: "finance" },
  });
  fireEvent.change(ui.getByLabelText("挂载路径"), {
    target: { value: "/mnt/finance" },
  });
  fireEvent.click(ui.getByRole("button", { name: "执行挂载文件系统" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0][2]).toMatchObject({
    action: "mount.create",
    parameters: {
      machine_id: "m1",
      target_user: "dingofs",
      fs_name: "finance",
      mount_path: "/mnt/finance",
      subdir: "/",
      use_rdma: false,
    },
  });
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("node-one"),
  );
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("/mnt/finance"),
  );
});

test("a pending operation is polled to completion and reveals structured filesystem results", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/resources")) return snapshot;
    if (path === "/resource-operations/op1")
      return {
        ...done,
        result: {
          steps: [
            {
              stdout: "raw row",
              stderr: "",
              returncode: 0,
              data: [{ fs_name: "polled-fs", capacity: 42 }],
            },
          ],
        },
      };
    return { ...done, state: "pending", result: null };
  });
  render(<ClusterResources {...props} />);
  const ui = await section("文件系统");
  // Entering the module starts the list operation automatically.
  expect(await screen.findByText("polled-fs")).toBeInTheDocument();
  expect(
    screen.getByRole("columnheader", { name: "capacity" }),
  ).toBeInTheDocument();
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(1);
  expect(ui.getByRole("button", { name: "刷新文件系统列表" })).toBeEnabled();
});

test("cancelling password authentication clears the challenge and shows non-rollback outcome", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/resources")) return snapshot;
    if (path.endsWith("/cancel"))
      return { ...done, state: "cancelled", result: null };
    return {
      ...done,
      state: "needs_password",
      result: null,
      challenge: "nonce",
      auth_account: "jenkins",
    };
  });
  render(<ClusterResources {...props} />);
  const ui = await section("文件系统");
  // Entering the module starts the list operation automatically.
  fireEvent.change(await screen.findByLabelText("认证密码"), {
    target: { value: "erase-on-cancel" },
  });
  fireEvent.click(screen.getByRole("button", { name: "取消等待" }));
  expect(await screen.findByText(/取消等待不会撤销/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/resource-operations/op1/cancel", "POST");
  expect(screen.queryByLabelText("认证密码")).not.toBeInTheDocument();
});

test("HTTP pages without randomUUID still send a valid UUID request ID", async () => {
  const randomUUID = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", {
    configurable: true,
    value: undefined,
  });
  try {
    render(<ClusterResources {...props} />);
    const ui = await section("缓存组");
    fireEvent.click(ui.getByRole("button", { name: "停止 fast-cache" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect((posts()[0][2] as { request_id: string }).request_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  } finally {
    Object.defineProperty(crypto, "randomUUID", {
      configurable: true,
      value: randomUUID,
    });
  }
});

test("cache member form initializes defaults supplied by the operation catalog", async () => {
  mockResponse({
    ...snapshot,
    catalog: catalog.map((item) =>
      item.action === "cache.create"
        ? {
            ...item,
            fields: item.fields.map((field) =>
              field.key === "members"
                ? {
                    ...field,
                    fields: [
                      {
                        key: "target_user",
                        type: "text",
                        default: "cache-owner",
                      },
                      { key: "listen_port", type: "number", default: 22001 },
                      { key: "cache_size_mb", type: "number", default: 2048 },
                    ],
                  }
                : field,
            ),
          }
        : item,
    ),
  });
  render(<ClusterResources {...props} />);
  const ui = await section("缓存组");
  expect(ui.getByLabelText("成员 1 执行用户")).toHaveValue("cache-owner");
  expect(ui.getByLabelText("成员 1 监听端口")).toHaveValue(22001);
  fireEvent.click(ui.getByRole("button", { name: "添加缓存成员" }));
  expect(ui.getByLabelText("成员 2 缓存容量 (MB)")).toHaveValue(2048);
});

test("partial saved resources have a clear outcome label", async () => {
  mockResponse({
    ...snapshot,
    resources: [{ ...snapshot.resources[0], state: "partial" }],
  });
  render(<ClusterResources {...props} />);
  const ui = await section("缓存组");
  expect(ui.getByRole("cell", { name: "部分完成，需核实" })).toBeVisible();
});

test("another user's pending operation cannot be polled or cancelled even by an administrator", async () => {
  vi.useFakeTimers();
  mockResponse({
    ...snapshot,
    operations: [
      { ...done, state: "pending", result: null, creator_id: "other-user" },
    ],
  });
  try {
    const { act } = await import("@testing-library/react");
    await act(async () => {
      render(<ClusterResources {...props} admin userId="current-user" />);
    });
    expect(screen.getByRole("button", { name: "取消等待" })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(api).toHaveBeenCalledTimes(1);
    expect(posts()).toHaveLength(0);
  } finally {
    vi.useRealTimers();
  }
});

test("refreshing saved records replaces the current operation's stale challenge", async () => {
  let refreshed = false;
  const challenge = {
    ...done,
    state: "needs_password",
    result: null,
    challenge: "nonce",
  };
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/resources")
      ? { ...snapshot, operations: refreshed ? [done] : [] }
      : challenge,
  );
  render(<ClusterResources {...props} />);
  const ui = await section("文件系统");
  // Entering the module starts the list operation automatically.
  expect(await screen.findByLabelText("认证密码")).toBeInTheDocument();
  refreshed = true;
  fireEvent.click(screen.getByRole("button", { name: "刷新已保存记录" }));
  await waitFor(() =>
    expect(screen.queryByLabelText("认证密码")).not.toBeInTheDocument(),
  );
  expect(
    within(screen.getByRole("region", { name: "当前结果" })).getByText(
      "已完成",
    ),
  ).toBeVisible();
});

test("catalog-driven quota fields preserve zero numeric values", async () => {
  const action = {
    action: "quota.dir.set",
    section: "filesystem",
    label: "设置目录配额",
    mutating: true,
    fields: [
      { key: "fs_name", label: "文件系统名称", type: "text", required: true },
      { key: "path", label: "目录路径", type: "text", default: "/" },
      { key: "capacity", label: "容量配额", type: "number", required: true },
      { key: "inodes", label: "inode 配额", type: "number", required: true },
    ],
  };
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/resources")
      ? { ...snapshot, catalog: [...catalog, action] }
      : {
          ...done,
          result: {
            steps: [
              {
                data: {
                  result: { fs_infos: [{ fs_name: "finance", fs_id: 42 }] },
                },
              },
            ],
          },
        },
  );
  render(<ClusterResources {...props} />);
  const ui = await choose("文件系统", "quota.dir.set");
  await ui.findByRole("option", { name: "finance" });
  fireEvent.change(ui.getByLabelText("文件系统名称"), {
    target: { value: "finance" },
  });
  fireEvent.change(ui.getByLabelText("容量配额"), { target: { value: "0" } });
  fireEvent.change(ui.getByLabelText("inode 配额"), { target: { value: "0" } });
  fireEvent.click(ui.getByRole("button", { name: "执行设置目录配额" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0][2]).toMatchObject({
    action: "quota.dir.set",
    parameters: { fs_name: "finance", path: "/", capacity: 0, inodes: 0 },
  });
});

test("only latest operation starts expanded and historical summaries retain time and status", async () => {
  mockResponse({
    ...snapshot,
    operations: [
      { ...done, id: "latest", created_at: "2026-09-24T09:20:41Z" },
      {
        ...done,
        id: "previous",
        created_at: "2026-09-24T09:20:23Z",
        state: "failed",
      },
    ],
  });
  render(<ClusterResources {...props} canManage={false} />);
  const history = await section("资源操作记录").then(() =>
    screen.getByRole("region", { name: "资源操作记录" }),
  );
  const records = history.querySelectorAll("details.resource-history-entry");
  expect(records).toHaveLength(2);
  expect(records[0]).toHaveAttribute("open");
  expect(records[1]).not.toHaveAttribute("open");
  expect(records[1].querySelector("summary")).toHaveTextContent("失败");
  expect(records[1].querySelector("summary time")).toHaveAttribute(
    "datetime",
    "2026-09-24T09:20:23Z",
  );
  expect(posts()).toHaveLength(0);
});

test("actions are grouped visibly and choosing an action reuses page filesystem choices", async () => {
  mockResponse({
    ...snapshot,
    catalog: [
      ...catalog,
      {
        action: "quota.fs.get",
        label: "查询文件系统配额",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
      {
        action: "quota.dir.get",
        label: "查询目录配额",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
      {
        action: "trash.get",
        label: "查询回收站",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
      {
        action: "dirstat.info",
        label: "目录信息",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
    ],
  });
  render(<ClusterResources {...props} />);
  const ui = await section("文件系统");
  for (const name of [
    "基础操作",
    "文件系统配额",
    "目录配额",
    "回收站",
    "目录统计",
  ])
    expect(ui.getByRole("button", { name })).toBeInTheDocument();
  expect(ui.queryByLabelText("操作")).not.toBeInTheDocument();
  fireEvent.click(ui.getByRole("button", { name: "目录配额" }));
  expect(
    ui.queryByRole("button", { name: "查询文件系统配额" }),
  ).not.toBeInTheDocument();
  fireEvent.click(ui.getByRole("button", { name: "查询目录配额" }));
  expect(ui.getByRole("button", { name: "查询目录配额" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    ui.getByRole("button", { name: "执行查询目录配额" }),
  ).toBeInTheDocument();
  expect(posts()).toHaveLength(0);
});

test("workspace shows one resource area and keeps history separate", async () => {
  mockResponse({ ...snapshot, operations: [done] });
  render(<ClusterResources {...props} />);
  const nav = await screen.findByRole("navigation", { name: "资源功能" });
  expect(screen.getByRole("region", { name: "文件系统" })).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "缓存组" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "资源操作记录" }),
  ).not.toBeInTheDocument();
  fireEvent.click(within(nav).getByRole("button", { name: /缓存组/ }));
  expect(screen.getByRole("region", { name: "缓存组" })).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "文件系统" }),
  ).not.toBeInTheDocument();
  fireEvent.click(within(nav).getByRole("button", { name: /操作记录/ }));
  expect(screen.getByRole("region", { name: "资源操作记录" })).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "缓存组" }),
  ).not.toBeInTheDocument();
  expect(posts()).toHaveLength(0);
});

test("history filters records without querying or rerunning remote commands", async () => {
  mockResponse({
    ...snapshot,
    operations: [
      { ...done, id: "ok", created_at: "2026-09-28T01:00:00Z" },
      {
        ...done,
        id: "bad",
        state: "failed",
        payload: { fs_name: "broken-fs" },
      },
    ],
  });
  render(<ClusterResources {...props} />);
  const nav = await screen.findByRole("navigation", { name: "资源功能" });
  fireEvent.click(within(nav).getByRole("button", { name: /操作记录/ }));
  fireEvent.change(screen.getByLabelText("操作状态"), {
    target: { value: "failed" },
  });
  expect(
    screen.getAllByRole("article", { name: "查询文件系统操作记录" }),
  ).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("搜索操作记录"), {
    target: { value: "absent" },
  });
  expect(screen.getByText("没有匹配的操作记录")).toBeVisible();
  expect(posts()).toHaveLength(0);
});

test("clicking the active feature preserves its form and does not execute", async () => {
  render(<ClusterResources {...props} />);
  const ui = await choose("文件系统", "fs.create");
  fireEvent.change(ui.getByLabelText("文件系统名称"), {
    target: { value: "keep-draft" },
  });
  // Add a second subgroup to exercise visible feature navigation.
  mockResponse({
    ...snapshot,
    catalog: [
      ...catalog,
      {
        action: "quota.fs.get",
        label: "查询文件系统配额",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
    ],
  });
  fireEvent.click(screen.getByRole("button", { name: "刷新已保存记录" }));
  fireEvent.click(await ui.findByRole("button", { name: "基础操作" }));
  expect(ui.getByLabelText("文件系统名称")).toHaveValue("keep-draft");
  expect(posts()).toHaveLength(0);
});

test("a catalogue without basic operations shows the fallback feature's result", async () => {
  mockResponse({
    ...snapshot,
    catalog: [
      {
        action: "quota.fs.get",
        label: "查询文件系统配额",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
    ],
    operations: [
      {
        ...done,
        action: "quota.fs.get",
        result: { steps: [{ stdout: "quota result", returncode: 0 }] },
      },
    ],
  });
  render(<ClusterResources {...props} />);
  expect(await screen.findByText("quota result")).toBeVisible();
});

test("polling continues while another area is visible and latest records stay ordered by time", async () => {
  const newer = {
    ...done,
    id: "newer",
    created_at: "2026-09-28T10:00:00Z",
    result: { steps: [{ stdout: "new result", returncode: 0 }] },
  };
  let finished = false;
  const pending = {
    ...done,
    id: "older",
    created_at: "2026-09-27T10:00:00Z",
    state: "pending",
    result: null,
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/resources"))
      return {
        ...snapshot,
        operations: [
          newer,
          finished ? { ...pending, state: "succeeded" } : pending,
        ],
      };
    finished = true;
    return { ...pending, state: "succeeded" };
  });
  render(<ClusterResources {...props} />);
  await section("缓存组");
  await waitFor(() => expect(finished).toBe(true));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "查看进度" }),
    ).not.toBeInTheDocument(),
  );
  await section("文件系统");
  expect(screen.getByText("new result")).toBeVisible();
  await section("资源操作记录");
  const entries = screen
    .getByRole("region", { name: "资源操作记录" })
    .querySelectorAll("details.resource-history-entry");
  expect(entries[0]).toHaveAttribute("open");
  expect(entries[0]).toHaveTextContent("new result");
  expect(entries[1]).not.toHaveAttribute("open");
  expect(posts()).toHaveLength(0);
});

test.each(["succeeded", "pending"])(
  "an older saved-record response cannot restore a challenge after authentication becomes %s",
  async (state) => {
    let resolveRefresh!: (value: unknown) => void;
    const staleRefresh = new Promise((resolve) => {
      resolveRefresh = resolve;
    });
    const challenge = {
      ...done,
      state: "needs_password",
      result: null,
      challenge: "old-nonce",
    };
    let loads = 0;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.endsWith("/resources")) {
        loads++;
        if (loads === 1) return snapshot;
        if (loads === 2) return staleRefresh;
        return { ...snapshot, operations: [done] };
      }
      if (path.endsWith("/authenticate")) return { ...done, state };
      return challenge;
    });
    render(<ClusterResources {...props} />);
    const ui = await section("文件系统");
    // Entering the module starts the list operation automatically.
    const password = await screen.findByLabelText("认证密码");
    fireEvent.click(screen.getByRole("button", { name: "刷新已保存记录" }));
    fireEvent.change(password, { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并继续" }));
    await waitFor(() =>
      expect(screen.queryByLabelText("认证密码")).not.toBeInTheDocument(),
    );
    if (state === "succeeded") await waitFor(() => expect(loads).toBe(3));
    await act(async () =>
      resolveRefresh({ ...snapshot, operations: [challenge] }),
    );
    expect(screen.queryByLabelText("认证密码")).not.toBeInTheDocument();
    if (state === "succeeded")
      expect(
        ui.getByRole("button", { name: "刷新文件系统列表" }),
      ).toBeEnabled();
  },
);
