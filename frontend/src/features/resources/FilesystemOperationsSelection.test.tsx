import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { actionGroup, sections } from "./workspace";
import type { ResourceOperation, ResourceSnapshot } from "./types";
import type { Execute } from "./useResourceWorkspace";
afterEach(cleanup);
function setup(
  action: string,
  key: "fs_id" | "fs_name",
  rows: Record<string, unknown>[] = [
    { fs_name: "active", fs_id: 42 },
    { fs_name: "old-DELETED", fs_id: 43 },
  ],
) {
  const list: ResourceOperation = {
    id: "list",
    action: "fs.list",
    state: "succeeded",
    result: { steps: [{ data: { result: { fs_infos: rows } } }] },
  };
  const snapshot: ResourceSnapshot = {
    machines: [],
    resources: [],
    operations: [],
    catalog: [
      {
        action: "fs.list",
        label: "列表",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
      {
        action,
        label: "目标操作",
        section: "filesystem",
        mutating: true,
        fields: [
          {
            key,
            label: key === "fs_id" ? "文件系统 ID" : "文件系统名称",
            type: key === "fs_id" ? "number" : "text",
            required: true,
          },
        ],
      },
    ],
  };
  const execute = vi.fn<Execute>(async (a, _v, _s, accepted) => {
    if (a.action === "fs.list") accepted?.(list);
  });
  render(
    <ResourceSectionForm
      section={sections[0]}
      snapshot={snapshot}
      disabled={false}
      execute={execute}
      group={actionGroup(action)}
      onGroupChange={() => {}}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "目标操作" }),
  );
  return execute;
}
test.each([
  ["quota.fs.get", "fs_name"],
  ["quota.fs.set", "fs_name"],
  ["quota.fs.delete", "fs_name"],
  ["quota.dir.get", "fs_name"],
  ["quota.dir.set", "fs_name"],
  ["quota.dir.delete", "fs_name"],
  ["trash.get", "fs_name"],
  ["trash.configure", "fs_name"],
  ["trash.restore", "fs_id"],
  ["dirstat.info", "fs_id"],
  ["dirstat.summary", "fs_id"],
  ["dirstat.enable", "fs_name"],
  ["dirstat.sync", "fs_id"],
] as const)("%s chooses filesystem and submits %s", async (action, key) => {
  const execute = setup(action, key);
  await screen.findByRole("option", { name: "active" });
  expect(execute.mock.calls[0][0].action).toBe("fs.list");
  expect(screen.queryByRole("option", { name: "old-DELETED" })).toBeNull();
  expect(screen.queryByRole("spinbutton", { name: "文件系统 ID" })).toBeNull();
  const submit = screen.getByRole("button", { name: "执行目标操作" });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "文件系统名称" }), {
    target: { value: "active" },
  });
  fireEvent.click(submit);
  expect(execute.mock.calls.at(-1)?.[1]).toEqual({
    [key]: key === "fs_id" ? 42 : "active",
  });
  fireEvent.click(screen.getByRole("button", { name: "刷新文件系统列表" }));
  await waitFor(() =>
    expect(
      execute.mock.calls.filter((call) => call[0].action === "fs.list"),
    ).toHaveLength(2),
  );
  expect(submit).toBeDisabled();
});
test.each([undefined, "invalid", 9007199254740992])(
  "invalid filesystem ID %s cannot be submitted",
  async (fs_id) => {
    setup("dirstat.info", "fs_id", [{ fs_name: "active", fs_id }]);
    await screen.findByRole("option", { name: "active" });
    fireEvent.change(screen.getByRole("combobox", { name: "文件系统名称" }), {
      target: { value: "active" },
    });
    expect(screen.getByRole("button", { name: "执行目标操作" })).toBeDisabled();
    expect(screen.getByText(/未返回有效的文件系统 ID/)).toBeInTheDocument();
  },
);
