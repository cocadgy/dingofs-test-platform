import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { Execute } from "./useResourceWorkspace";
import type { ResourceSnapshot } from "./types";
afterEach(cleanup);
function setup(state: number | number[] = 1, groupName = "g") {
  const execute = vi.fn<Execute>(async () => {});
  const snapshot: ResourceSnapshot = {
    machines: [],
    catalog: [
      ...["cache.leave", "cache.unlock", "cache.weight"].map(action => ({action, label:action, section:"cache" as const, mutating:true, fields:[]})),
      {
        action: "cache.list",
        label: "缓存组与成员列表",
        section: "cache",
        mutating: false,
        fields: [],
      },
      {
        action: "cache.stop",
        label: "停止缓存组",
        section: "cache",
        mutating: true,
        fields: [{ key: "resource_id", label: "资源", type: "text" }],
      },
      {
        action: "cache.delete",
        label: "删除缓存组成员登记",
        section: "cache",
        mutating: true,
        fields: [{ key: "member_id", label: "缓存组成员", type: "text" }],
      },
      {
        action: "cache.delete_batch",
        label: "批量删除",
        section: "cache",
        mutating: true,
        fields: [],
      },
    ],
    resources: ["a", "b"].map((id) => ({
      id: "r-" + id,
      kind: "cache",
      name: "g",
      state: "running",
      created_at: "",
      data: {
        members: [{ member_id: id, machine_id: "m", target_user: "root" }],
      },
    })),
    operations: [
      {
        id: "list",
        action: "cache.list",
        state: "succeeded",
        result: {
          steps: [
            {
              data: {
                groups: { result: { group_names: ["g"] } },
                members: {
                  result: {
                    members: ["a", "b"].map((id, i) => ({
                      member_id: id,
                      group_name: groupName,
                      ip: "192.0.2.1",
                      port: 21000 + i,
                      state: Array.isArray(state) ? state[i] : state,
                    })),
                  },
                },
              },
            },
          ],
        },
      },
    ],
  };
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={snapshot}
      execute={execute}
      disabled={false}
      group="缓存组操作"
      onGroupChange={vi.fn()}
    />,
  );
  return execute;
}
test("group stop targets members from multiple creation records", () => {
  const execute = setup();
  fireEvent.click(screen.getByRole("button", { name: "平滑停止 g" }));
  expect(execute.mock.calls[0]?.[1]).toEqual({ member_ids: ["a", "b"] });
});
test("expanded member stop only targets that UUID", async () => {
  const execute = setup();
  fireEvent.click(screen.getByText("成员信息"));
  const table = within(
    await screen.findByRole("table", { name: "g 成员列表" }),
  );
  fireEvent.click(table.getByRole("button", { name: "停止成员 a" }));
  expect(execute.mock.calls[0]?.[1]).toEqual({ member_ids: ["a"] });
});
test("member delete and group delete have distinct fixed targets", async () => {
  const execute = setup(3);
  fireEvent.click(screen.getByText("成员信息"));
  fireEvent.click(await screen.findByRole("button", { name: "删除成员 a" }));
  expect(execute.mock.calls[0]?.[1]).toEqual({ member_id: "a" });
  fireEvent.click(screen.getByRole("button", { name: "删除 g" }));
  expect(execute.mock.calls[1]?.[1]).toEqual({ member_ids: ["a", "b"] });
});

test("external member with an authorized machine target can stop without a creation record", () => {
  const operation = {
    id: "q",
    action: "cache.list",
    state: "succeeded",
    result: {
      steps: [
        {
          data: {
            members: {
              result: {
                members: [
                  {
                    member_id: "external",
                    group_name: "g",
                    ip: "192.0.2.1",
                    port: 21000,
                    state: 1,
                  },
                ],
              },
            },
          },
        },
      ],
    },
  };
  const execute = vi.fn<Execute>(async () => {});
  render(
    <ResourceSectionForm
      section={sections[1]}
      disabled={false}
      execute={execute}
      group="缓存组操作"
      onGroupChange={vi.fn()}
      snapshot={{
        machines: [],
        resources: [],
        operations: [operation],
        cache_member_targets: {
          external: { machine_id: "m", target_user: "root", can_stop: true },
        },
        catalog: [
          {
            action: "cache.stop",
            label: "停止缓存组",
            section: "cache",
            mutating: true,
            fields: [],
          },
          {
            action: "cache.list",
            label: "缓存组与成员列表",
            section: "cache",
            mutating: false,
            fields: [],
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "平滑停止 g" }));
  expect(execute.mock.calls[0]?.[1]).toEqual({ member_ids: ["external"] });
});

test("offline members and entirely offline group cannot be stopped", async () => {
  const execute = setup(3);
  expect(screen.getByRole("button", { name: "平滑停止 g" })).toBeDisabled();
  fireEvent.click(screen.getByText("成员信息"));
  const stop = await screen.findByRole("button", { name: "停止成员 a" });
  expect(stop).toBeDisabled();
  fireEvent.click(stop);
  expect(execute).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "删除成员 a" })).toBeEnabled();
});

test("group stop excludes offline members", () => {
  const execute = setup([1, 3]);
  fireEvent.click(screen.getByRole("button", { name: "平滑停止 g" }));
  expect(execute.mock.calls[0]?.[1]).toEqual({ member_ids: ["a"] });
});


test("ungrouped member deletion submits only its UUID through the existing action", () => {
  const execute = setup(3, "");
  fireEvent.click(screen.getByRole("button", { name: "删除成员 a" }));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({action:"cache.delete", label:expect.stringContaining("未分组")}), {member_id:"a"});
});
test("online ungrouped members cannot be deleted", () => {
  const execute = setup(1, "");
  expect(screen.getByRole("button", {name:"删除成员 a"})).toBeDisabled();
  expect(execute).not.toHaveBeenCalled();
});

test("delete all ungrouped uses batch deletion and skips online members", () => {
  const execute = setup([3,1], "");
  fireEvent.click(screen.getByRole("button", {name:"删除所有未分组成员"}));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({action:"cache.delete_batch",label:expect.stringContaining("跳过 1")}), {member_ids:["a"]});
});
test("delete all ungrouped is disabled when only grouped members exist", () => {
  setup(3);
  expect(screen.getByRole("button",{name:"删除所有未分组成员"})).toBeDisabled();
});


test("leave member submits UUID and group identity without stopping process", () => {
  const execute = setup();
  fireEvent.click(screen.getByRole("button", {name:"成员信息"}));
  fireEvent.click(screen.getByRole("button", {name:"离开缓存组成员 a"}));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({action:"cache.leave"}), {member_id:"a",group_name:"g"});
});
test("ungrouped member supports unlock and weight but not leave", () => {
  const execute = setup(3, "");
  expect(screen.queryByRole("button",{name:"离开缓存组成员 a"})).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"解锁成员 a"}));
  expect(execute).toHaveBeenLastCalledWith(expect.objectContaining({action:"cache.unlock"}),{member_id:"a",group_name:""});
  const prompt = vi.spyOn(window,"prompt").mockReturnValue("125");
  fireEvent.click(screen.getByRole("button",{name:"设置权重成员 a"}));
  expect(execute).toHaveBeenLastCalledWith(expect.objectContaining({action:"cache.weight"}),{member_id:"a",group_name:"",weight:125});
  prompt.mockRestore();
});


test("force stop explicitly submits force for all selected group members", () => {
  const execute=setup();
  fireEvent.click(screen.getByRole("button", {name:"强制停止 g"}));
  expect(execute).toHaveBeenCalledWith(expect.objectContaining({action:"cache.stop", label:expect.stringContaining("kill -9")}),{member_ids:["a","b"],force:true});
});
