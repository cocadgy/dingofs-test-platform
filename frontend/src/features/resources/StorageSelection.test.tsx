import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { ResourceSnapshot } from "./types";

afterEach(cleanup);
const profile = {
  id: "s3",
  name: "共享测试 S3",
  storage_type: "s3" as const,
  description: "测试存储",
  enabled: true,
  revision: 2,
  creator_id: "other-user",
  can_manage: false,
  has_secrets: true,
  parameters: {
    s3_endpoint: "http://s3.test:9000",
    s3_bucketname: "test-bucket",
  },
  created_at: "2026-10-08T00:00:00Z",
  updated_at: "2026-10-08T00:00:00Z",
};
const snapshot: ResourceSnapshot = {
  machines: [],
  resources: [],
  operations: [],
  storage_profiles: [
    profile,
    { ...profile, id: "disabled", name: "停用存储", enabled: false },
  ],
  catalog: [
    {
      action: "fs.create",
      label: "创建文件系统",
      section: "filesystem",
      mutating: true,
      fields: [
        { key: "fs_name", label: "文件系统名称", type: "text", required: true },
        {
          key: "partition_type",
          label: "分区类型",
          type: "select",
          default: "hash",
          options: ["hash", "monolithic"],
        },
        {
          key: "storage_type",
          label: "存储类型",
          type: "select",
          options: ["s3", "rados"],
        },
        { key: "s3_ak", label: "S3 Access Key", type: "password" },
        { key: "storage_profile_id", label: "存储配置", type: "text" },
        { key: "storage_profile_revision", label: "版本", type: "number" },
      ],
    },
  ],
};
function setup(next = snapshot) {
  const execute = vi.fn(async () => {});
  const props = {
    section: sections[0],
    snapshot: next,
    disabled: false,
    execute,
    group: "基础操作",
    onGroupChange: vi.fn(),
  };
  return { ...render(<ResourceSectionForm {...props} />), execute, props };
}
test("create selects shared storage and sends its identity without credentials", () => {
  const { execute } = setup();
  const button = screen.getByRole("button", { name: "执行创建文件系统" });
  expect(button).toBeDisabled();
  expect(screen.queryByLabelText("S3 Access Key")).toBeNull();
  expect(screen.queryByRole("option", { name: /停用存储/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("文件系统名称"), {
    target: { value: "new-fs" },
  });
  fireEvent.change(screen.getByLabelText("存储配置"), {
    target: { value: "s3" },
  });
  expect(screen.getByText("http://s3.test:9000")).toBeInTheDocument();
  expect(screen.getByText("test-bucket")).toBeInTheDocument();
  fireEvent.click(button);
  expect(execute).toHaveBeenCalledWith(
    expect.anything(),
    {
      fs_name: "new-fs",
      partition_type: "hash",
      storage_profile_id: "s3",
      storage_profile_revision: 2,
    },
    expect.any(Function),
  );
});
test("no storage requires registration, and changed or disabled selection blocks create", () => {
  const { props, rerender } = setup({ ...snapshot, storage_profiles: [] });
  expect(screen.getByText(/尚无可用存储配置/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "管理存储配置" })).toHaveAttribute(
    "href",
    "#/storage",
  );
  rerender(<ResourceSectionForm {...props} snapshot={snapshot} />);
  fireEvent.change(screen.getByLabelText("存储配置"), {
    target: { value: "s3" },
  });
  rerender(
    <ResourceSectionForm
      {...props}
      snapshot={{
        ...snapshot,
        storage_profiles: [{ ...profile, revision: 3 }],
      }}
    />,
  );
  expect(
    screen.getByRole("button", { name: "执行创建文件系统" }),
  ).toBeDisabled();
  expect(screen.getByText(/已变更或停用/)).toBeInTheDocument();
});

test("RADOS selection previews its connection and preserves filesystem input", () => {
  const { execute } = setup({
    ...snapshot,
    storage_profiles: [
      {
        ...profile,
        id: "rados",
        name: "测试 RADOS",
        storage_type: "rados",
        parameters: {
          rados_mon: "10.0.0.1:6789,10.0.0.2:6789",
          rados_poolname: "pool-a",
          rados_username: "client.test",
          rados_clustername: "cluster-a",
        },
      },
    ],
  });
  fireEvent.change(screen.getByLabelText("文件系统名称"), {
    target: { value: "rados-fs" },
  });
  fireEvent.change(screen.getByLabelText("存储配置"), {
    target: { value: "rados" },
  });
  expect(screen.getByText("pool-a")).toBeInTheDocument();
  expect(screen.getByText("10.0.0.1:6789,10.0.0.2:6789")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "执行创建文件系统" }));
  expect(execute).toHaveBeenCalledWith(
    expect.anything(),
    {
      fs_name: "rados-fs",
      partition_type: "hash",
      storage_profile_id: "rados",
      storage_profile_revision: 2,
    },
    expect.any(Function),
  );
});
