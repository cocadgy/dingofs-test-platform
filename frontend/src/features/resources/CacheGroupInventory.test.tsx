import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { ResourceNavigation } from "./ResourceNavigation";
import { sections } from "./workspace";
import type { ResourceSnapshot } from "./types";

afterEach(cleanup);
function snapshot(): ResourceSnapshot {
  const names = Array.from(
    { length: 30 },
    (_, i) => `vdbench_cache_group-${i}`,
  );
  return {
    machines: [],
    catalog: [
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
    ],
    resources: [
      {
        id: "failed",
        kind: "cache",
        name: "test1",
        state: "deleted",
        created_at: "2026-10-09",
        data: { members: [{}] },
      },
    ],
    operations: [
      {
        id: "q",
        action: "cache.list",
        state: "succeeded",
        created_at: "2026-10-09T07:22:14Z",
        result: {
          steps: [
            {
              data: {
                groups: { result: { group_names: names } },
                members: {
                  result: {
                    members: names.flatMap((group_name, i) =>
                      [0, 1].map((n) => ({
                        group_name,
                        member_id: `member-${i}-${n}`,
                        ip: "192.0.2.1",
                        port: 21000 + n,
                        state: 3,
                      })),
                    ),
                  },
                },
              },
            },
          ],
        },
      },
    ],
  };
}
function show(data = snapshot()) {
  return render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={data}
      disabled={false}
      execute={vi.fn(async () => {})}
      group="缓存组操作"
      onGroupChange={vi.fn()}
    />,
  );
}

test("actual stopped groups replace failed or deleted local creation records", () => {
  show();
  const table = within(screen.getByRole("table", { name: "缓存组列表" }));
  expect(table.getAllByRole("row")).toHaveLength(31);
  expect(
    table.getByRole("rowheader", { name: "vdbench_cache_group-29" }),
  ).toBeVisible();
  expect(table.getAllByRole("cell", { name: "已停止" })).toHaveLength(30);
  expect(table.getAllByRole("cell", { name: "2" })).toHaveLength(60);
  expect(screen.queryByText("test1", { exact: true })).toBeNull();
  expect(
    screen.getByRole("button", { name: "平滑停止 vdbench_cache_group-0" }),
  ).toBeDisabled();
});

test("cache navigation counts discovered groups instead of local attempts", () => {
  render(
    <ResourceNavigation
      area="cache"
      snapshot={snapshot()}
      operationCount={1}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: /缓存组/ })).toHaveTextContent(
    "30",
  );
});

test("groups mentioned only in members remain visible and ungrouped members are not fictitious groups", () => {
  const data = snapshot();
  data.operations[0].result = {
    steps: [
      {
        data: {
          groups: { result: { group_names: ["empty-group"] } },
          members: {
            result: {
              members: [
                {
                  member_id: "a",
                  group_name: "stopped-group",
                  ip: "192.0.2.1",
                  port: 21000,
                  state: 3,
                },
                {
                  member_id: "b",
                  group_name: "",
                  ip: "192.0.2.1",
                  port: 21001,
                  state: 3,
                },
              ],
            },
          },
        },
      },
    ],
  };
  show(data);
  const table = within(screen.getByRole("table", { name: "缓存组列表" }));
  expect(table.getAllByRole("row")).toHaveLength(3);
  expect(table.getByRole("rowheader", { name: "stopped-group" })).toBeVisible();
  expect(table.getByRole("rowheader", { name: "empty-group" })).toBeVisible();
  const members = within(screen.getByRole("table", { name: "缓存成员列表" }));
  expect(members.getAllByRole("row")).toHaveLength(3);
  expect(members.getByRole("cell", { name: "b" })).toBeVisible();
  expect(members.getByRole("cell", { name: "未分组" })).toBeVisible();
  expect(members.getByRole("cell", { name: "192.0.2.1:21001" })).toBeVisible();
});

test("failed queries are not replaced by a fake local cache inventory", () => {
  const data = snapshot();
  data.operations[0] = {
    ...data.operations[0],
    state: "failed",
    message: "MDS 查询失败",
  };
  show(data);
  expect(screen.queryByRole("table", { name: "缓存组列表" })).toBeNull();
  expect(screen.queryByText("test1", { exact: true })).toBeNull();
  expect(screen.getByText("MDS 查询失败")).toBeVisible();
});

test("only a matching nondeleted managed group offers process stop", () => {
  const data = snapshot();
  data.resources.push({
    id: "managed",
    kind: "cache",
    name: "vdbench_cache_group-0",
    state: "running",
    created_at: "2026-10-09",
    data: {
      members: [{ member_id: "member-0-0" }, { member_id: "member-0-1" }],
    },
  });
  show(data);
  expect(
    screen.getByRole("button", { name: "平滑停止 vdbench_cache_group-0" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "平滑停止 vdbench_cache_group-1" }),
  ).toBeDisabled();
});

test("completed deletion removes the entire group but preserves partial failures and unknown outcomes", () => {
  const data = snapshot();
  data.operations.unshift({
    id: "del",
    action: "cache.delete_batch",
    state: "failed",
    created_at: "2026-10-09T08:00:00Z",
    result: {
      steps: [
        { member_id: "member-0-0", failed: false },
        { member_id: "member-0-1", failed: false },
        { member_id: "member-1-0", failed: false },
        { member_id: "member-1-1", failed: true },
      ],
    },
  });
  show(data);
  const table = within(screen.getByRole("table", { name: "缓存组列表" }));
  expect(
    table.queryByRole("rowheader", { name: "vdbench_cache_group-0" }),
  ).toBeNull();
  expect(
    table.getByRole("rowheader", { name: "vdbench_cache_group-1" }),
  ).toBeVisible();
  expect(
    within(
      table
        .getByRole("rowheader", { name: "vdbench_cache_group-1" })
        .closest("tr")!,
    ).getAllByRole("cell", { name: "1" })[0],
  ).toBeVisible();
  expect(
    table.getByRole("rowheader", { name: "vdbench_cache_group-2" }),
  ).toBeVisible();
  render(
    <ResourceNavigation
      area="cache"
      snapshot={data}
      operationCount={2}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: /缓存组\s*29/ })).toBeVisible();
});


test("add member reveals and focuses the creation form with the selected group", () => {
  const data = snapshot();
  data.catalog.push({action:"cache.create",label:"创建缓存组",section:"cache",mutating:true,
    fields:[{key:"group_name",label:"缓存组名称",type:"text",required:true}]});
  show(data);
  const table=within(screen.getByRole("table",{name:"缓存组列表"}));
  const row=table.getByRole("rowheader",{name:"vdbench_cache_group-0"}).closest("tr")!;
  fireEvent.click(within(row).getByRole("button",{name:"添加成员"}));
  expect(screen.getByRole("textbox",{name:"缓存组名称"})).toHaveValue("vdbench_cache_group-0");
  expect(screen.getByRole("form",{name:"资源操作表单"})).toHaveFocus();
  expect(screen.getByText(/正在向缓存组「vdbench_cache_group-0」添加成员/)).toBeVisible();
});

test("group capacity sums member MiB in GiB without treating missing data as zero", () => {
  const data = snapshot();
  data.resources.push({id:"capacity",kind:"cache",name:"vdbench_cache_group-0",state:"running",created_at:"",data:{members:[
    {member_id:"member-0-0",cache_size_mb:1024},{member_id:"member-0-1",cache_size_mb:512},
  ]}});
  show(data);
  const table=within(screen.getByRole("table",{name:"缓存组列表"}));
  expect(table.getByRole("columnheader",{name:"总容量（GiB）"})).toBeVisible();
  const row=table.getByRole("rowheader",{name:"vdbench_cache_group-0"}).closest("tr")!;
  expect(within(row).getByRole("cell",{name:"1.5"})).toBeVisible();
  const unknown=table.getByRole("rowheader",{name:"vdbench_cache_group-1"}).closest("tr")!;
  expect(within(unknown).getByRole("cell",{name:"未获取"})).toBeVisible();
});
