import { StrictMode, useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { ResourceAction, ResourceSnapshot } from "./types";
import type { Execute } from "./useResourceWorkspace";
afterEach(cleanup);
const actions: ResourceAction[] = [
  {
    action: "fs.list",
    label: "列表",
    section: "filesystem",
    mutating: false,
    fields: [],
  },
  ...[
    "fs.get",
    "fs.delete",
    "quota.fs.get",
    "quota.fs.set",
    "quota.dir.get",
    "trash.get",
    "dirstat.enable",
  ].map((action) => ({
    action,
    label: action,
    section: "filesystem" as const,
    mutating: false,
    fields: [{ key: "fs_name", label: "文件系统名称", type: "text" as const }],
  })),
];
function setup() {
  const execute = vi.fn<Execute>(async (a, _v, _s, accepted) => {
    if (a.action === "fs.list")
      accepted?.({
        id: "list-" + execute.mock.calls.length,
        action: "fs.list",
        state: "succeeded",
        result: {
          steps: [{ data: { fs_infos: [{ fs_name: "data", fs_id: 42 }] } }],
        },
      });
  });
  function Harness() {
    const [group, setGroup] = useState("基础操作");
    const [visible, setVisible] = useState(true);
    const snapshot: ResourceSnapshot = {
      catalog: actions,
      operations: [],
      machines: [],
      resources: [],
    };
    return (
      <>
        <button onClick={() => setVisible(!visible)}>切换页面</button>
        <div hidden={!visible}>
          <ResourceSectionForm
            section={sections[0]}
            snapshot={snapshot}
            disabled={false}
            execute={execute}
            group={group}
            onGroupChange={setGroup}
          />
        </div>
      </>
    );
  }
  render(
    <StrictMode>
      <Harness />
    </StrictMode>,
  );
  return execute;
}
test("fetch once per page, reuse across modules and tabs, and refresh only explicitly", async () => {
  const execute = setup();
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "fs.get" }));
  await screen.findByRole("option", { name: "data" });
  fireEvent.click(screen.getByRole("button", { name: "fs.delete" }));
  fireEvent.click(screen.getByRole("button", { name: "fs.delete" }));
  expect(execute).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "刷新文件系统列表" }));
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2));
  for (const group of [
    "文件系统配额",
    "目录配额",
    "回收站",
    "目录统计",
    "基础操作",
  ]) {
    const before = execute.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: group }));
    await waitFor(() => expect(execute).toHaveBeenCalledTimes(before));
  }
  fireEvent.click(screen.getByRole("button", { name: "文件系统配额" }));
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "quota.fs.set" }));
  expect(execute).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "切换页面" }));
  fireEvent.click(screen.getByRole("button", { name: "切换页面" }));
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2));
});

test("an entry query remains usable after switching modules while it is pending", async () => {
  const execute = setup();
  let finishOld: (() => void) | undefined;
  execute.mockImplementationOnce(
    (_action, _values, _submitted, accepted) =>
      new Promise<void>((resolve) => {
        finishOld = () => {
          accepted?.({
            id: "old",
            action: "fs.list",
            state: "succeeded",
            result: {
              steps: [{ data: { fs_infos: [{ fs_name: "obsolete" }] } }],
            },
          });
          resolve();
        };
      }),
  );
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "文件系统配额" }));
  expect(execute).toHaveBeenCalledTimes(1);
  finishOld?.();
  await screen.findByRole("option", { name: "obsolete" });
  expect(execute).toHaveBeenCalledTimes(1);
});
