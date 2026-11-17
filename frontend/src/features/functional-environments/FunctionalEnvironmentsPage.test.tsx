import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { FunctionalEnvironmentsPage } from "./FunctionalEnvironmentsPage";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
beforeEach(() => {
  window.location.hash = "#/configuration/test-environments";
  vi.resetAllMocks();
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/functional/environments"
      ? [
          {
            id: "e1",
            name: "env_126_base",
            source_kind: "predefined",
            source_file: "env_126.yaml",
            revision: 1,
            enabled: false,
            validation: "template",
            display: { client_count: 1, storage_type: "s3" },
            can_manage: false,
          },
        ]
      : path === "/functional/options"
        ? { clusters: [] }
        : path === "/storage-profiles"
          ? []
          : { items: [] },
  );
});
test("shows predefined environments in configuration management", async () => {
  render(<FunctionalEnvironmentsPage onDirty={() => {}} />);
  expect(await screen.findByText("env_126_base")).toBeTruthy();
  expect(screen.getByText("基础模板")).toBeTruthy();
});

test("renders all presets and opens a copy form without mutating source", async () => {
  const presets = Array.from({ length: 100 }, (_, i) => ({
    id: String(i),
    name: `env_${i}`,
    source_kind: "predefined",
    source_file: "source.yaml",
    revision: 1,
    enabled: i > 0,
    validation: i === 0 ? "template" : "source_only",
    settings: {},
    display: { client_count: 1, storage_type: "s3" },
    can_manage: false,
  }));
  vi.mocked(api).mockImplementation(async (path) =>
    String(path).endsWith("/copy-settings")
      ? { settings: {}, warnings: [] }
      : path === "/functional/environments"
        ? presets
        : path === "/functional/options"
          ? { clusters: [{ id: "c", name: "集群" }] }
          : path === "/storage-profiles"
            ? [{ id: "s", name: "S3", enabled: true, can_manage: true }]
            : {
                items: [
                  {
                    id: "m",
                    name: "机器",
                    address: "10.0.0.1",
                    can_manage: true,
                  },
                ],
              },
  );
  const dirty = vi.fn();
  render(<FunctionalEnvironmentsPage onDirty={dirty} />);
  expect((await screen.findAllByText(/env_\d+/)).length).toBe(100);
  fireEvent.click(screen.getAllByRole("button", { name: "复制为自建" })[0]);
  expect(
    await screen.findByRole("heading", { name: "复制预置环境" }),
  ).toBeTruthy();
  expect(dirty).toHaveBeenCalledWith(true);
  expect(
    screen
      .getByRole("button", { name: "保存测试环境" })
      .hasAttribute("disabled"),
  ).toBe(true);
});

test("creates a one-client custom environment from selected resources", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/environments" && method === "POST")
      return { id: "created" };
    if (path === "/functional/environments") return [];
    if (path === "/functional/options")
      return { clusters: [{ id: "cluster", name: "测试集群" }] };
    if (path === "/storage-profiles")
      return [
        { id: "storage", name: "测试存储", enabled: true, can_manage: true },
      ];
    return {
      items: [
        {
          id: "machine",
          name: "测试机",
          address: "10.0.0.1",
          can_manage: true,
        },
      ],
    };
  });
  render(<FunctionalEnvironmentsPage onDirty={() => {}} />);
  const create = await screen.findByRole("button", { name: "新建测试环境" });
  await (
    await import("@testing-library/react")
  ).waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "new-env" },
  });
  fireEvent.change(screen.getByLabelText("测试集群"), {
    target: { value: "cluster" },
  });
  fireEvent.change(screen.getByLabelText("测试机"), {
    target: { value: "machine" },
  });
  fireEvent.change(screen.getByLabelText("存储配置"), {
    target: { value: "storage" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存测试环境" }));
  const { waitFor } = await import("@testing-library/react");
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.find(
          (c) => c[0] === "/functional/environments" && c[1] === "POST",
        )?.[2],
    ).toMatchObject({
      name: "new-env",
      cluster_id: "cluster",
      machine_id: "machine",
      storage_profile_id: "storage",
      settings: { client_count: 1 },
    }),
  );
});

test("includes selected client and cache machines when saving", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/environments" && method === "POST")
      return { id: "created" };
    if (path === "/functional/environments") return [];
    if (path === "/functional/options")
      return { clusters: [{ id: "cluster", name: "测试集群" }] };
    if (path === "/storage-profiles")
      return [
        { id: "storage", name: "测试存储", enabled: true, can_manage: true },
      ];
    return {
      items: [
        {
          id: "machine",
          name: "测试机",
          address: "10.0.0.1",
          can_manage: true,
        },
      ],
    };
  });
  render(<FunctionalEnvironmentsPage onDirty={() => {}} />);
  const create = await screen.findByRole("button", { name: "新建测试环境" });
  await (
    await import("@testing-library/react")
  ).waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "multi-env" },
  });
  fireEvent.change(screen.getByLabelText("测试集群"), {
    target: { value: "cluster" },
  });
  fireEvent.change(screen.getByLabelText("测试机"), {
    target: { value: "machine" },
  });
  fireEvent.change(screen.getByLabelText("存储配置"), {
    target: { value: "storage" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加客户端配置" }));
  fireEvent.click(screen.getByRole("button", { name: "添加缓存配置" }));
  fireEvent.click(screen.getByRole("button", { name: "保存测试环境" }));
  const { waitFor } = await import("@testing-library/react");
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.find(
          (c) => c[0] === "/functional/environments" && c[1] === "POST",
        )?.[2],
    ).toMatchObject({
      settings: {
        clients: [{ machine_id: "machine" }],
        remote_caches: [{ machine_id: "machine" }],
      },
    }),
  );
});

test("shows ready and failed states and actual custom client totals", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/functional/environments"
      ? [
          {
            id: "ready",
            name: "已通过环境",
            source_kind: "custom",
            settings: {
              clients: [{ client_count: 3 }, { client_count: 2 }],
              remote_caches: [{ remote_cache_count: 4 }],
            },
            display: {},
            validation: "ready",
            enabled: true,
            can_manage: true,
          },
          {
            id: "failed",
            name: "失败环境",
            source_kind: "custom",
            settings: {},
            display: {},
            validation: "failed",
            enabled: true,
            can_manage: true,
          },
        ]
      : path === "/functional/options"
        ? { clusters: [] }
        : path === "/storage-profiles"
          ? []
          : { items: [] },
  );
  render(<FunctionalEnvironmentsPage onDirty={() => {}} />);
  expect(await screen.findByText("验证通过")).toBeInTheDocument();
  expect(screen.getByText("验证失败")).toBeInTheDocument();
  expect(screen.getByText("5 客户端 · 4 缓存成员")).toBeInTheDocument();
});
test("locks environment editing while save is pending", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "PUT") return new Promise(() => {});
    if (path === "/functional/environments")
      return [
        {
          id: "edit",
          name: "环境",
          source_kind: "custom",
          revision: 1,
          cluster_id: "c",
          machine_id: "m",
          storage_profile_id: "s",
          settings: { mount_root: "/tmp/x", fs_prefix: "test" },
          display: {},
          enabled: true,
          can_manage: true,
        },
      ];
    if (path === "/functional/options")
      return { clusters: [{ id: "c", name: "集群" }] };
    if (path === "/storage-profiles")
      return [{ id: "s", name: "存储", enabled: true, can_manage: true }];
    return { items: [{ id: "m", name: "机器", can_manage: true }] };
  });
  render(<FunctionalEnvironmentsPage onDirty={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
  fireEvent.click(screen.getByRole("button", { name: "保存测试环境" }));
  expect(screen.getByLabelText("名称")).toBeDisabled();
  expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
});
