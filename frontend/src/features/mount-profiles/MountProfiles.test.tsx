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
