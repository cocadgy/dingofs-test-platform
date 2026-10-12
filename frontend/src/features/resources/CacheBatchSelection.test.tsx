import {renderHook} from "@testing-library/react";
import {useCacheMemberListing} from "./useCacheMemberListing";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { ResourceSnapshot } from "./types";
afterEach(cleanup);
function setup(count = 2) {
  const execute = vi.fn<import("./useResourceWorkspace").Execute>(
    async () => {},
  );
  const members = [
    ...Array.from({ length: count }, (_, i) => ({
      member_id: `id-${i}`,
      group_name: "vdbench_cache_group-a",
      ip: "192.0.2.1",
      port: 21000 + i,
      state: 3,
    })),
    { member_id: "online", group_name: "vdbench_cache_group-a", state: 1 },
  ];
  const snapshot: ResourceSnapshot = {
    resources: [],
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
        action: "cache.delete_batch",
        label: "通配符批量删除缓存成员",
        section: "cache",
        mutating: true,
        fields: [
          {
            key: "member_ids",
            label: "待删除成员",
            type: "names",
            required: true,
          },
        ],
      },
    ],
    operations: [
      {
        id: "q",
        action: "cache.list",
        state: "succeeded",
        created_at: "2026-10-09T00:00:00Z",
        result: { steps: [{ data: { members: { result: { members } } } }] },
      },
    ],
  };
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={snapshot}
      disabled={false}
      execute={execute}
      group="缓存组操作"
      onGroupChange={vi.fn()}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "通配符批量删除缓存成员" }),
  );
  return execute;
}
test("match group names, exclude online members, and submit only checked member IDs", () => {
  const execute = setup();
  const button = screen.getByRole("button", {
    name: "执行通配符批量删除缓存成员",
  });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("缓存组名或成员 ID 通配符"), {
    target: { value: "vdbench*" },
  });
  expect(screen.getByRole("checkbox", { name: /online/ })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /id-1/ }));
  fireEvent.click(button);
  expect(execute.mock.calls[0][1]).toEqual({ member_ids: ["id-0"] });
});
test("limit batches to 100 and support matching an exact member ID", () => {
  setup(101);
  const input = screen.getByLabelText("缓存组名或成员 ID 通配符");
  const button = screen.getByRole("button", {
    name: "执行通配符批量删除缓存成员",
  });
  fireEvent.change(input, { target: { value: "vdbench*" } });
  expect(button).toBeDisabled();
  fireEvent.change(input, { target: { value: "id-100" } });
  expect(button).toBeEnabled();
});

test("partial batch results hide successful deletions only", () => {
  const query = {id:"q",action:"cache.list",state:"succeeded",created_at:"2026-10-09T00:00:00Z",result:{steps:[{data:{members:{result:{members:["a","b","c"].map(member_id=>({member_id,group_name:"batch",state:3}))}}}}]}};
  const snapshot: ResourceSnapshot = {resources:[],machines:[],catalog:[],operations:[{id:"delete",action:"cache.delete_batch",state:"failed",created_at:"2026-10-09T00:01:00Z",payload:{member_ids:["a","b","c"]},result:{steps:[{member_id:"a",failed:false},{member_id:"b",failed:true}]}},query]};
  const {result} = renderHook(()=>useCacheMemberListing(snapshot,vi.fn()));
  expect(result.current.options.map(member=>member.id)).toEqual(["b","c"]);
});
