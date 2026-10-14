import { useState } from "react";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {MountProfilesPage} from "./MountProfilesPage";
import {MountProfileSelection} from "./MountProfileSelection";
import {api} from "../../api/client";
vi.mock("../../api/client",()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const catalog={source_version:"test",fields:[{name:"fuse_max_threads",type:"uint32",group:"FUSE",label:"线程数",description:"threads",default:"64",managed:null,member_key:null}]};
const profile={id:"p",name:"mount-base",description:"",enabled:true,parameters:{fuse_max_threads:"16"},revision:2,creator_id:"u",can_manage:true,source_version:"test",updated_at:""};
test("mount configuration page loads its own catalogue",async()=>{
  vi.mocked(api).mockImplementation(async path=>path.endsWith("catalog")?catalog:[profile]);
  render(<MountProfilesPage onDirty={vi.fn()}/>);
  await waitFor(()=>expect(screen.getByText("mount-base")).toBeVisible());
  expect(api).toHaveBeenCalledWith("/mount-profiles/catalog");
  expect(screen.getByRole("heading",{name:"挂载配置"})).toBeVisible();
});
test("selecting a mount profile copies parameters and revision",()=>{
  const change=vi.fn();
  render(<MountProfileSelection profiles={[profile]} catalog={catalog} values={{}} disabled={false} onChange={change}/>);
  fireEvent.change(screen.getByRole("combobox",{name:"选择挂载配置"}),{target:{value:"p"}});
  expect(change).toHaveBeenCalledWith({mount_profile_id:"p",mount_profile_revision:2,mount_options:{fuse_max_threads:"16"}});
  expect(profile.parameters.fuse_max_threads).toBe("16");
});

test("saving current mount options creates and selects a reusable profile",async()=>{
  const change=vi.fn();
  const created={...profile,id:"new",name:"my-mount",revision:1,parameters:{fuse_max_threads:"32"}};
  vi.mocked(api).mockResolvedValue(created);
  function Selection() {
    const [values,setValues]=useState({mount_options:{fuse_max_threads:"32"}});
    return <MountProfileSelection profiles={[profile]} catalog={catalog} values={values} disabled={false} onChange={patch=>{change(patch);setValues(previous=>({...previous,...patch}));}}/>;
  }
  render(<Selection/>);
  fireEvent.click(screen.getByText("调整本次挂载参数"));
  fireEvent.change(screen.getByRole("textbox",{name:"新配置名称"}),{target:{value:"my-mount"}});
  fireEvent.click(screen.getByRole("button",{name:"保存到挂载配置"}));
  await waitFor(()=>expect(api).toHaveBeenCalledWith("/mount-profiles","POST",{
    name:"my-mount",description:"",enabled:true,parameters:{fuse_max_threads:"32"},
  }));
  await waitFor(()=>expect(change).toHaveBeenCalledWith({mount_profile_id:"new",mount_profile_revision:1}));
  expect(screen.getByRole("combobox",{name:"选择挂载配置"})).toHaveValue("new");
});

test("saving rejects duplicate names before creating a profile",()=>{
  render(<MountProfileSelection profiles={[profile]} catalog={catalog} values={{}} disabled={false} onChange={vi.fn()}/>);
  fireEvent.click(screen.getByText("调整本次挂载参数"));
  fireEvent.change(screen.getByRole("textbox",{name:"新配置名称"}),{target:{value:"mount-base"}});
  fireEvent.click(screen.getByRole("button",{name:"保存到挂载配置"}));
  expect(screen.getByRole("alert")).toHaveTextContent("名称已存在");
  expect(api).not.toHaveBeenCalled();
});
