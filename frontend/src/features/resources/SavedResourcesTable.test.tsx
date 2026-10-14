import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SavedResourcesTable } from "./SavedResourcesTable";
import type { ResourceAction, ResourceMachine, SavedResource } from "./types";

afterEach(cleanup);

const machines: ResourceMachine[] = [
  {
    id: "m1",
    name: "storage-one",
    address: "10.0.0.1",
    ssh_user: "jenkins",
    can_manage: true,
  },
];
const cache: SavedResource = {
  id: "cache1",
  kind: "cache",
  name: "fast-cache",
  state: "running",
  data: {
    members: [{ machine_id: "m1" }, { machine_id: "m2" }],
    operation_id: "op-hidden",
  },
  created_at: "2026-01-01",
};
const mount: SavedResource = {
  id: "mount1",
  kind: "mount",
  name: "data-mount",
  state: "mounted",
  data: {
    fs_name: "research-fs",
    mount_path: "/mnt/research",
    machine_id: "m1",
  },
  created_at: "2026-01-02",
};
const actions: ResourceAction[] = [
  {
    action: "cache.stop",
    label: "停止缓存组",
    section: "cache",
    mutating: true,
    fields: [],
  },
  {
    action: "cache.delete",
    label: "删除缓存组",
    section: "cache",
    mutating: true,
    fields: [],
  },
  {
    action: "mount.status",
    label: "查看挂载状态",
    section: "mount",
    mutating: false,
    fields: [],
  },
  {
    action: "mount.unmount",
    label: "卸载文件系统",
    section: "mount",
    mutating: true,
    fields: [],
  },
  {
    action: "mount.logs",
    label: "客户端日志",
    section: "mount",
    mutating: false,
    fields: [],
  },
];

function renderTable(
  resources: SavedResource[],
  options: { disabled?: boolean; actions?: ResourceAction[] } = {},
) {
  const onAction = vi.fn();
  render(
    <SavedResourcesTable
      resources={resources}
      machines={machines}
      actions={options.actions ?? actions}
      disabled={options.disabled ?? false}
      onAction={onAction}
    />,
  );
  return onAction;
}

test("cache rows summarize members and lazily expand saved fields", async () => {
  renderTable([cache]);
  const table = screen.getByRole("table", { name: "已保存资源" });
  expect(
    within(table).getByRole("rowheader", { name: "fast-cache" }),
  ).toBeInTheDocument();
  expect(within(table).getByRole("cell", { name: "2" })).toBeInTheDocument();
  expect(
    within(table).getByRole("cell", { name: "执行中" }),
  ).toBeInTheDocument();
  const details = screen.getByText("保存的资源信息").closest("details");
  expect(details).not.toHaveAttribute("open");
  expect(screen.queryByText("op-hidden")).toBeNull();
  fireEvent.click(screen.getByText("保存的资源信息"));
  expect(details).toContainElement(await screen.findByText("op-hidden"));
});

test("mount rows show the filesystem, path, and machine name with an ID fallback", () => {
  renderTable([
    mount,
    {
      ...mount,
      id: "mount2",
      name: "old-mount",
      data: {
        fs_name: "archive-fs",
        mount_path: "/mnt/archive",
        machine_id: "removed-machine",
      },
    },
  ]);
  const table = screen.getByRole("table", { name: "已保存资源" });
  expect(
    within(table).getByRole("cell", { name: "research-fs" }),
  ).toBeInTheDocument();
  expect(
    within(table).getByRole("cell", { name: "/mnt/research" }),
  ).toBeInTheDocument();
  expect(
    within(table).getByRole("cell", { name: "storage-one" }),
  ).toBeInTheDocument();
  expect(
    within(table).getByRole("cell", { name: "removed-machine" }),
  ).toBeInTheDocument();
  expect(
    within(table).queryByRole("columnheader", { name: "成员数" }),
  ).not.toBeInTheDocument();
});

test("search matches names and mount context while state filtering combines with it", () => {
  renderTable([
    cache,
    mount,
    { ...mount, id: "mount2", name: "old-mount", state: "unmounted" },
  ]);
  const search = screen.getByRole("searchbox", { name: "搜索资源" });
  for (const query of [
    "DATA-MOUNT",
    "research-fs",
    "/mnt/research",
    "storage-one",
  ]) {
    fireEvent.change(search, { target: { value: ` ${query} ` } });
    expect(
      screen.getByRole("rowheader", { name: "data-mount" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("rowheader", { name: "fast-cache" }),
    ).not.toBeInTheDocument();
  }
  fireEvent.change(screen.getByRole("combobox", { name: "筛选资源状态" }), {
    target: { value: "mounted" },
  });
  expect(
    screen.getByRole("rowheader", { name: "data-mount" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("rowheader", { name: "old-mount" }),
  ).not.toBeInTheDocument();
  fireEvent.change(search, { target: { value: "missing" } });
  expect(screen.getByText("没有匹配的资源。")).toBeInTheDocument();
});

test("only catalog actions are shown and each shortcut passes the selected resource", () => {
  const onAction = renderTable([cache, mount], {
    actions: actions.filter((action) => action.action !== "cache.delete"),
  });
  expect(
    screen.queryByRole("button", { name: "删除 fast-cache" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "平滑停止 fast-cache" }));
  expect(onAction).toHaveBeenLastCalledWith(cache, "cache.stop");
  for (const [label, action] of [
    ["状态", "mount.status"],
    ["卸载", "mount.unmount"],
    ["日志", "mount.logs"],
  ]) {
    fireEvent.click(
      screen.getByRole("button", { name: `${label} data-mount` }),
    );
    expect(onAction).toHaveBeenLastCalledWith(mount, action);
  }
  expect(onAction).toHaveBeenCalledTimes(4);
});

test("disabled resources cannot invoke actions but remain searchable", () => {
  const onAction = renderTable([cache, mount], { disabled: true });
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
    fireEvent.click(button);
  }
  expect(onAction).not.toHaveBeenCalled();
  expect(screen.getByRole("searchbox", { name: "搜索资源" })).toBeEnabled();
});

test("missing member data and empty inventories have explicit fallbacks", () => {
  const { unmount } = render(
    <SavedResourcesTable
      resources={[{ ...cache, data: {} }]}
      machines={[]}
      actions={[]}
      disabled={false}
      onAction={() => {}}
    />,
  );
  expect(
    within(screen.getByRole("table", { name: "已保存资源" })).getByRole(
      "cell",
      { name: "—" },
    ),
  ).toBeInTheDocument();
  unmount();
  renderTable([]);
  expect(screen.getByText("暂无保存的资源记录。")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

test("mount status filter and colors distinguish mounted from unmounted", () => {
  renderTable([mount, { ...mount, id: "old", name: "old-mount", state: "unmounted" }]);
  const mounted = screen.getByRole("cell", { name: "已挂载" }).querySelector(".badge");
  const unmounted = screen.getByRole("cell", { name: "已卸载" }).querySelector(".badge");
  expect(mounted).toHaveClass("resource-state-mounted");
  expect(unmounted).toHaveClass("resource-state-unmounted");
  fireEvent.change(screen.getByRole("combobox", { name: "筛选资源状态" }), { target: { value: "unmounted" } });
  expect(screen.getByRole("rowheader", { name: "old-mount" })).toBeInTheDocument();
  expect(screen.queryByRole("rowheader", { name: "data-mount" })).not.toBeInTheDocument();
});

test("unmounted client cannot be unmounted again, but logs remain available", () => {
  const old = { ...mount, state: "unmounted" };
  const onAction = renderTable([old]);
  const unmount = screen.getByRole("button", { name: "卸载 data-mount" });
  expect(unmount).toBeDisabled();
  fireEvent.click(unmount);
  expect(onAction).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "日志 data-mount" })).toBeEnabled();
});


test("unmounted clients can remount and mounted clients link to their actual config port", () => {
  const unmounted = { ...mount, id: "mount2", name: "old-mount", state: "unmounted" };
  const onAction = renderTable([
    { ...mount, data: { ...mount.data, vfs_dummy_server_port: 10007 } },
    unmounted,
  ], { actions: [...actions, { action: "mount.remount", label: "重新挂载", section: "mount", mutating: true, fields: [] }] });
  expect(screen.getByRole("link", { name: "data-mount" })).toHaveAttribute("href", "http://10.0.0.1:10007/");
  expect(screen.queryByRole("link", { name: "old-mount" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新挂载 data-mount" }));
  expect(onAction).toHaveBeenLastCalledWith({ ...mount, data: { ...mount.data, vfs_dummy_server_port: 10007 } }, "mount.remount");
  fireEvent.click(screen.getByRole("button", { name: "重新挂载 old-mount" }));
  expect(onAction).toHaveBeenCalledWith(unmounted, "mount.remount");
});

test("batch client selection follows filter and disables incompatible actions", () => {
  const batch=vi.fn();
  render(<SavedResourcesTable resources={[mount,{...mount,id:"m2",name:"stopped",state:"unmounted"}]}
    machines={machines} actions={[...actions,{action:"mount.delete",label:"删除记录",section:"mount",mutating:true,fields:[]}]}
    disabled={false} onAction={vi.fn()} onBatchAction={batch}/>);
  fireEvent.change(screen.getByLabelText("筛选资源状态"),{target:{value:"mounted"}});
  fireEvent.click(screen.getByLabelText("全选当前资源"));
  fireEvent.click(screen.getByRole("button",{name:"批量卸载"}));
  expect(batch).toHaveBeenCalledWith("mount.unmount",["mount1"]);
  expect(screen.getByRole("button",{name:"批量删除记录"})).toBeDisabled();
});

test("cache group and nested member checkboxes share selection",()=>{
  const batch=vi.fn();
  const resource={...cache,data:{queried_inventory:true,members:[
    {member_id:"one",state:"在线",can_stop:true,selectable:false},
    {member_id:"two",state:"离线",can_stop:false,selectable:true},
  ]}};
  render(<SavedResourcesTable queried resources={[resource]} machines={machines}
    actions={[...actions,{action:"cache.delete_batch",label:"删除成员",section:"cache",mutating:true,fields:[]}]}
    disabled={false} onAction={vi.fn()} onBatchAction={batch}/>);
  fireEvent.click(screen.getByRole("button",{name:"成员信息"}));
  fireEvent.click(screen.getByLabelText("选择成员 one"));
  fireEvent.click(screen.getByRole("button",{name:"批量强制停止"}));
  expect(batch).toHaveBeenCalledWith("cache.force_stop",["one"]);
  fireEvent.click(screen.getByLabelText("选择成员 two"));
  expect(screen.getByRole("button",{name:"批量平滑停止"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"批量删除成员"})).toBeDisabled();
  fireEvent.click(screen.getByLabelText("全选成员 fast-cache"));
  expect(screen.getByText("已选择 0 项")).toBeVisible();
});
