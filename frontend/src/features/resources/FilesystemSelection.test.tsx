import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { filesystemNames } from "./filesystemOptions";
import type { ResourceOperation, ResourceSnapshot } from "./types";
import type { Execute } from "./useResourceWorkspace";
import { sections } from "./workspace";

const snapshot: ResourceSnapshot = {
  resources: [],
  machines: [],
  operations: [],
  catalog: [
    {
      action: "fs.list",
      label: "文件系统列表",
      section: "filesystem",
      mutating: false,
      fields: [],
    },
    ...["get", "delete", "create"].map((kind) => ({
      action: `fs.${kind}`,
      label: (
        {
          get: "文件系统详情",
          delete: "删除文件系统",
          create: "创建文件系统",
        } as Record<string, string>
      )[kind],
      section: "filesystem" as const,
      mutating: kind !== "get",
      fields: [
        {
          key: "fs_name",
          label: "文件系统名称",
          type: "text" as const,
          required: true,
        },
      ],
    })),
  ],
};
const listing = (names: string[]): ResourceOperation => ({
  id: "list-1",
  action: "fs.list",
  state: "succeeded",
  result: {
    steps: [
      { data: { result: { fs_infos: names.map((fs_name) => ({ fs_name })) } } },
    ],
  },
});
function setup(result = listing(["alpha", "beta"])) {
  const execute = vi.fn<Execute>(
    async (action, _values, _submitted, accepted) => {
      if (action.action === "fs.list") accepted?.(result);
    },
  );
  const props = {
    section: sections[0],
    snapshot,
    disabled: false,
    execute,
    group: "基础操作",
    onGroupChange: vi.fn(),
  };
  return { execute, props, ...render(<ResourceSectionForm {...props} />) };
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("details and delete share the entry list and submit only a selected name", async () => {
  const { execute } = setup();
  fireEvent.click(screen.getByRole("button", { name: "文件系统详情" }));
  await screen.findByRole("option", { name: "alpha" });
  expect(execute.mock.calls[0][0].action).toBe("fs.list");
  expect(
    screen.getByRole("button", { name: "执行文件系统详情" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("文件系统名称"), {
    target: { value: "beta" },
  });
  fireEvent.click(screen.getByRole("button", { name: "执行文件系统详情" }));
  expect(execute.mock.calls[1][0].action).toBe("fs.get");
  expect(execute.mock.calls[1][1]).toEqual({ fs_name: "beta" });
  fireEvent.click(screen.getByRole("button", { name: "删除文件系统" }));
  await screen.findByRole("option", { name: "alpha" });
  expect(
    execute.mock.calls.filter((call) => call[0].action === "fs.list"),
  ).toHaveLength(1);
  expect(screen.getByLabelText("文件系统名称")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("文件系统名称"), {
    target: { value: "alpha" },
  });
  fireEvent.click(screen.getByRole("button", { name: "执行删除文件系统" }));
  expect(execute.mock.calls[2][1]).toEqual({ fs_name: "alpha" });
});

test("pending list follows its own operation through polling updates", async () => {
  const { props, rerender } = setup({ ...listing([]), state: "running" });
  fireEvent.click(screen.getByRole("button", { name: "文件系统详情" }));
  await waitFor(() => expect(props.execute).toHaveBeenCalledTimes(1));
  expect(
    screen.getByRole("button", { name: "执行文件系统详情" }),
  ).toBeDisabled();
  rerender(
    <ResourceSectionForm
      {...props}
      snapshot={{ ...snapshot, operations: [listing(["fresh"])] }}
    />,
  );
  await screen.findByRole("option", { name: "fresh" });
});

test("empty and failed results block deletion and allow refresh", async () => {
  const { execute } = setup(listing([]));
  fireEvent.click(screen.getByRole("button", { name: "删除文件系统" }));
  await screen.findByText("暂无文件系统");
  expect(
    screen.getByRole("button", { name: "执行删除文件系统" }),
  ).toBeDisabled();
  execute.mockImplementation(async (_a, _v, _s, accepted) =>
    accepted?.({ ...listing([]), state: "failed", message: "MDS 不可达" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "刷新文件系统列表" }));
  await screen.findByText("MDS 不可达");
  expect(
    screen.getByRole("button", { name: "执行删除文件系统" }),
  ).toBeDisabled();
});

test("create retains free text and reuses the entry list", async () => {
  const { execute } = setup();
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "创建文件系统" }));
  expect(
    screen.getByRole("textbox", { name: "文件系统名称" }),
  ).toBeInTheDocument();
  expect(execute).toHaveBeenCalledTimes(1);
});

test("list parser accepts raw JSON, deduplicates, and rejects unrecognized data", () => {
  expect(
    filesystemNames({
      ...listing([]),
      result: {
        steps: [
          {
            stdout: JSON.stringify({
              fs_infos: [{ fs_name: "b" }, { fs_name: "a" }, { fs_name: "a" }],
            }),
          },
        ],
      },
    }),
  ).toEqual(["a", "b"]);
  expect(() =>
    filesystemNames({
      ...listing([]),
      result: { steps: [{ data: { message: "not a list" } }] },
    }),
  ).toThrow("无法识别");
});

test("switching away ignores an older list response", async () => {
  let finish: (() => void) | undefined;
  const { execute } = setup();
  execute.mockImplementation(
    (_a, _v, _s, accepted) =>
      new Promise<void>((resolve) => {
        finish = () => {
          accepted?.(listing(["obsolete"]));
          resolve();
        };
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "文件系统详情" }));
  fireEvent.click(screen.getByRole("button", { name: "创建文件系统" }));
  finish?.();
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "文件系统名称" }),
    ).toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("option", { name: "obsolete" }),
  ).not.toBeInTheDocument();
});

test("shell wildcard batch deletion uses full matches and only checked snapshot names", async () => {
  const batch = {
    action: "fs.delete_batch",
    label: "通配符批量删除",
    section: "filesystem" as const,
    mutating: true,
    fields: [{ key: "fs_names", label: "名单", type: "names" as const }],
  };
  snapshot.catalog.push(batch);
  try {
    const { execute } = setup(
      listing(["test-a", "test-b", "prefix-test-a", "production"]),
    );
    fireEvent.click(screen.getByRole("button", { name: "通配符批量删除" }));
    await waitFor(() =>
      expect(screen.getByLabelText("文件系统名通配符")).not.toBeDisabled(),
    );
    const input = screen.getByLabelText("文件系统名通配符");
    const submit = screen.getByRole("button", { name: "执行通配符批量删除" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "[" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "test-*" } });
    expect(
      screen.queryByRole("checkbox", { name: "prefix-test-a" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "test-b" }));
    fireEvent.click(submit);
    expect(execute.mock.calls.at(-1)?.[1]).toEqual({ fs_names: ["test-a"] });
    fireEvent.change(input, { target: { value: "nothing" } });
    expect(submit).toBeDisabled();
  } finally {
    snapshot.catalog.pop();
  }
});

test("deleted filesystem names are excluded from all selectors and batch candidates", () => {
  expect(
    filesystemNames(
      listing(["normal", "DELETED-old", "old-DELETED-123", "suffixDELETED"]),
    ),
  ).toEqual(["normal"]);
  expect(filesystemNames(listing(["DELETED-old"]))).toEqual([]);
});
