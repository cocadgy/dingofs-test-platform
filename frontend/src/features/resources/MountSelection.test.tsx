import {ResourceSectionForm} from "./ResourceSectionForm";
import {sections} from "./workspace";
import type {ResourceSnapshot, ResourceOperation} from "./types";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {ResourceFields} from "./ResourceFields";
import {selectsFilesystem} from "./filesystemOptions";
afterEach(cleanup);
test("mount selects filesystem and optional cache group from query options", () => {
  const change=vi.fn();
  render(<ResourceFields action={{action:"mount.create",label:"挂载",section:"mount" as const,mutating:true,fields:[
    {key:"fs_name",label:"文件系统名称",type:"text",required:true},
    {key:"cache_group",label:"缓存组名称",type:"text" as const},
  ]}} values={{fs_name:"",cache_group:""}} machines={[]} resources={[]} disabled={false}
  filesystemOptions={["fs-a","fs-b"]} cacheGroupOptions={["group-a"]} onChange={change} />);
  expect(selectsFilesystem("mount.create")).toBe(true);
  fireEvent.change(screen.getByRole("combobox",{name:"文件系统名称"}),{target:{value:"fs-a"}});
  expect(change).toHaveBeenLastCalledWith("fs_name","fs-a");
  fireEvent.change(screen.getByRole("combobox",{name:"缓存组名称"}),{target:{value:"group-a"}});
  expect(change).toHaveBeenLastCalledWith("cache_group","group-a");
  expect(screen.getByRole("option",{name:"不指定缓存组"})).toBeVisible();
  expect(screen.queryByRole("textbox",{name:"文件系统名称"})).toBeNull();
});

test("a removed cache group stays visibly selected as invalid until the user reselects", () => {
  const change=vi.fn();
  const action={action:"mount.create",label:"挂载",section:"mount" as const,mutating:true,fields:[
    {key:"cache_group",label:"缓存组名称",type:"text" as const},
  ]};
  const values={cache_group:"group-a"};
  const props={action,values,machines:[],resources:[],disabled:false,onChange:change};
  const {rerender}=render(<ResourceFields {...props} cacheGroupOptions={["group-a"]} />);
  rerender(<ResourceFields {...props} cacheGroupOptions={[]} />);
  expect(screen.getByRole("combobox",{name:"缓存组名称"})).toHaveValue("group-a");
  expect(screen.getByRole("option",{name:/已失效/})).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/重新选择/);
  fireEvent.change(screen.getByRole("combobox",{name:"缓存组名称"}),{target:{value:""}});
  expect(change).toHaveBeenCalledWith("cache_group","");
});

test("mount submit is blocked when a refreshed cache list drops the selected group", async () => {
  const list = (id:string, names:string[]): ResourceOperation => ({
    id, action:"cache.list", state:"succeeded", created_at:`2026-10-12T00:00:0${id === "first" ? "1" : "2"}Z`,
    result:{steps:[{data:{groups:{result:{group_names:names}},members:{result:{members:[]}}}}]},
  } as ResourceOperation);
  const mount = {action:"mount.create",label:"挂载文件系统",section:"mount",mutating:true,fields:[
    {key:"fs_name",label:"文件系统名称",type:"text",required:true},
    {key:"cache_group",label:"缓存组名称",type:"text"},
  ]};
  const fs = {action:"fs.list",label:"查询文件系统",section:"filesystem",mutating:false,fields:[]};
  const base = {catalog:[mount,fs], machines:[], resources:[], operations:[list("first",["group-a"])], cache_member_targets:{}} as unknown as ResourceSnapshot;
  const execute=vi.fn(async (action: {action:string}, _values:unknown, _done?:unknown, accepted?: (result:ResourceOperation)=>void) => {
    if (action.action === "fs.list") accepted?.({id:"fs",action:"fs.list",state:"succeeded",result:{steps:[{data:{fs_infos:[{fs_name:"fs-a"}]}}]}} as ResourceOperation);
  });
  const props={section:sections.find(item=>item.key === "mount")!,disabled:false,execute,group:"挂载操作",onGroupChange:vi.fn()};
  const {rerender}=render(<ResourceSectionForm {...props} snapshot={base} />);
  fireEvent.click(screen.getByRole("button",{name:"刷新文件系统列表"}));
  await screen.findByRole("option",{name:"fs-a"});
  fireEvent.change(screen.getByRole("combobox",{name:"文件系统名称"}),{target:{value:"fs-a"}});
  fireEvent.change(screen.getByRole("combobox",{name:"缓存组名称"}),{target:{value:"group-a"}});
  const submit=screen.getByRole("button",{name:"执行挂载文件系统"});
  expect(submit).toBeEnabled();
  rerender(<ResourceSectionForm {...props} snapshot={{...base,operations:[list("second",[]),...base.operations]}} />);
  await waitFor(()=>expect(submit).toBeDisabled());
  expect(screen.getByRole("combobox",{name:"缓存组名称"})).toHaveValue("group-a");
  fireEvent.click(submit);
  expect(execute).toHaveBeenCalledTimes(1);
});

test("unmount choices contain only mounted filesystem records", () => {
  const resources = [
    { id: "mounted", kind: "mount" as const, name: "/mnt/a", state: "mounted", data: { fs_name: "fs-a" }, created_at: "" },
    { id: "unmounted", kind: "mount" as const, name: "/mnt/b", state: "unmounted", data: { fs_name: "fs-b" }, created_at: "" },
    { id: "unknown", kind: "mount" as const, name: "/mnt/c", state: "unknown", data: { fs_name: "fs-c" }, created_at: "" },
  ];
  const action = { action: "mount.unmount", label: "卸载文件系统", section: "mount" as const, mutating: true,
    fields: [{ key: "resource_id", label: "资源 ID", type: "text" as const, required: true }] };
  render(<ResourceFields action={action} values={{ resource_id: "" }} machines={[]} resources={resources} disabled={false} onChange={vi.fn()} />);
  const selection = screen.getByRole("combobox", { name: "选择挂载点" });
  expect(selection).toHaveTextContent("/mnt/a");
  expect(selection).not.toHaveTextContent("/mnt/b");
  expect(selection).not.toHaveTextContent("/mnt/c");
});

test("unmount submit becomes unavailable if the selected record is no longer mounted", () => {
  const action = { action: "mount.unmount", label: "卸载文件系统", section: "mount" as const, mutating: true,
    fields: [{ key: "resource_id", label: "资源 ID", type: "text" as const, required: true }] };
  const record = { id: "mount-1", kind: "mount" as const, name: "/mnt/a", state: "mounted", data: { fs_name: "fs-a" }, created_at: "" };
  const snapshot = { catalog: [action], machines: [], resources: [record], operations: [] } as ResourceSnapshot;
  const props = { section: sections.find(item => item.key === "mount")!, group: "挂载操作", onGroupChange: vi.fn(),
    disabled: false, execute: vi.fn(async () => {}) };
  const { rerender } = render(<ResourceSectionForm {...props} snapshot={snapshot} />);
  fireEvent.change(screen.getByRole("combobox", { name: "选择挂载点" }), { target: { value: "mount-1" } });
  const submit = screen.getByRole("button", { name: "执行卸载文件系统" });
  expect(submit).toBeEnabled();
  rerender(<ResourceSectionForm {...props} snapshot={{ ...snapshot, resources: [{ ...record, state: "unmounted" }] }} />);
  expect(submit).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "选择挂载点" })).toHaveValue("");
  expect(screen.getByRole("alert")).toHaveTextContent("不再是已挂载状态");
});
