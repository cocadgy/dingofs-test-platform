import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { ResourceHistory } from "./ResourceHistory";
import { BatchActions } from "./BatchSelection";
import { sections } from "./workspace";
import type { ResourceAction, ResourceSnapshot } from "./types";
afterEach(cleanup);
const list = {
  id: "fs-latest",
  action: "fs.list",
  state: "succeeded",
  created_at: "2026-10-15T09:00:00Z",
  result: {
    steps: [
      {
        data: {
          fs_infos: [
            {
              fs_name: "data",
              fs_id: 42,
              status: 1,
              capacity: 1073741824,
              block_size: 4096,
            },
          ],
        },
      },
    ],
  },
};
const field = { key: "fs_name", label: "文件系统名称", type: "text" as const };
const action = (
  key: string,
  label: string,
  section: "filesystem" | "mount" | "cache",
  fields: ResourceAction["fields"] = [],
): ResourceAction => ({
  action: key,
  label,
  section,
  fields,
  mutating: !key.endsWith(".list"),
});
const snapshot = (catalog: ResourceAction[]): ResourceSnapshot => ({
  catalog,
  resources: [],
  machines: [],
  operations: [list],
});
test("mount consumes the shared filesystem query without another command", () => {
  const execute = vi.fn();
  render(
    <ResourceSectionForm
      section={sections[2]}
      snapshot={snapshot([
        action("mount.create", "挂载文件系统", "mount", [field]),
      ])}
      disabled={false}
      execute={execute}
      group="挂载操作"
      onGroupChange={() => {}}
    />,
  );
  expect(screen.getByRole("option", { name: "data" })).toBeInTheDocument();
  expect(execute).not.toHaveBeenCalled();
});
test("filesystem inventory is the primary view with readable status and actions", () => {
  render(
    <ResourceSectionForm
      section={sections[0]}
      snapshot={snapshot([
        action("fs.list", "文件系统列表", "filesystem"),
        action("fs.get", "文件系统详情", "filesystem", [field]),
      ])}
      disabled
      execute={vi.fn()}
      group="基础操作"
      onGroupChange={() => {}}
    />,
  );
  const table = screen.getByRole("table", { name: "文件系统资源列表" });
  expect(within(table).getByText("正常")).toBeVisible();
  expect(within(table).getByText("data")).toBeVisible();
  expect(screen.getByText(/最近查询/)).toBeVisible();
});
test("automatic list refresh does not replace the last failed mutation", () => {
  render(
    <ResourceHistory
      area="cache"
      selectedGroup="缓存组操作"
      operations={[
        {
          id: "q",
          action: "cache.list",
          state: "succeeded",
          result: { steps: [{ stdout: "refresh-success" }] },
        },
        {
          id: "f",
          action: "cache.create",
          state: "failed",
          result: { steps: [{ stderr: "port-conflict" }] },
        },
      ]}
      catalog={[action("cache.create", "创建缓存组", "cache")]}
      canManage={false}
      onChange={() => {}}
      onShowHistory={() => {}}
      historySearch=""
      setHistorySearch={() => {}}
      historyState=""
      setHistoryState={() => {}}
    />,
  );
  expect(screen.getByText("port-conflict")).toBeVisible();
  expect(screen.queryByText("refresh-success")).not.toBeInTheDocument();
});
test("switching commands preserves the creation draft", () => {
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={snapshot([
        action("cache.create", "创建缓存组", "cache", [
          { key: "group_name", label: "缓存组名称", type: "text" },
        ]),
        action("cache.leave", "成员离开缓存组", "cache"),
      ])}
      disabled={false}
      execute={vi.fn()}
      group="缓存组操作"
      onGroupChange={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("缓存组名称"), {
    target: { value: "draft-group" },
  });
  fireEvent.click(screen.getByRole("button", { name: "成员离开缓存组" }));
  fireEvent.click(screen.getByRole("button", { name: "创建缓存组" }));
  expect(screen.getByLabelText("缓存组名称")).toHaveValue("draft-group");
});
test("batch selection explicitly identifies selected rows hidden by filters", () => {
  render(
    <BatchActions
      picked={["a", "b"]}
      visibleIds={["a"]}
      choices={[]}
      disabled={false}
      onAction={() => {}}
      onClear={() => {}}
    />,
  );
  expect(screen.getByText(/1 项不在当前筛选结果中/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "查看已选" }));
  expect(screen.getByText("b")).toBeVisible();
});
test("cache defaults to listing instead of leave or another mutation", () => {
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={snapshot([
        action("cache.leave", "成员离开缓存组", "cache"),
        action("cache.list", "缓存组与成员列表", "cache"),
      ])}
      disabled={false}
      execute={vi.fn()}
      group="缓存组操作"
      onGroupChange={() => {}}
    />,
  );
  expect(
    screen.getByRole("button", { name: "缓存组与成员列表" }),
  ).toHaveAttribute("aria-pressed", "true");
});
