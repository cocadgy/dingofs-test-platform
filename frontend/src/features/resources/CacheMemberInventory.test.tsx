import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { CacheMemberInventory } from "./CacheMemberInventory";
afterEach(cleanup);
test("ungrouped members remain visible without groups and can be filtered", () => {
  render(<CacheMemberInventory members={[
    {id:"orphan",groupName:"",address:"192.0.2.1:9000",stateLabel:"在线",selectable:false},
    {id:"joined",groupName:"g",address:"192.0.2.2:9000",stateLabel:"离线",selectable:true},
  ]} />);
  const table = within(screen.getByRole("table",{name:"缓存成员列表"}));
  expect(table.getByText("orphan")).toBeVisible();
  fireEvent.change(screen.getByRole("combobox",{name:"成员范围"}),{target:{value:"ungrouped"}});
  expect(table.queryByText("joined")).toBeNull();
  expect(table.getByText("未分组")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox",{name:"搜索成员"}),{target:{value:"missing"}});
  expect(screen.getByText("没有符合筛选条件的成员。")).toBeVisible();
});
test("empty member query shows an explicit empty state", () => {
  render(<CacheMemberInventory members={[]} />);
  expect(screen.getByText("当前没有缓存成员。")).toBeVisible();
});

test("capacity shows its configured source and zero weight is preserved", () => {
  render(<CacheMemberInventory members={[{id:"m",groupName:"",address:"host:1",stateLabel:"离线",selectable:true,weight:0}]}
    resources={[{id:"r",kind:"cache",name:"old-group",state:"running",created_at:"",data:{members:[{member_id:"m",cache_size_mb:1024}]}}]} />);
  expect(screen.getByRole("cell",{name:"1024 MiB（平台配置）"})).toBeVisible();
  expect(screen.getByRole("cell",{name:"0"})).toBeVisible();
});
