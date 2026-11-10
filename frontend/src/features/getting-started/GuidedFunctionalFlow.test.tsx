import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../../App";
import { api } from "../../api/client";
import { CaseSelector } from "../functional/CaseSelector";
import { PreflightStep } from "../functional/PreflightStep";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
const digest = "a".repeat(64);
const descriptor = { env_name: "env_one", source_manifest: {}, digest, mds_addresses: ["node:6900"],
  targets: [{role: "client", host: "node", user: "tester", mutates: true}],
  client_count: null, cache_count: null, storage_type: "s3",
  programs: {client: "/opt/client"}, directories: {mount: "/mnt/test"}, modules: {}, issues: [] };
const profiles = [
  {id:"e1",name:"env_one",revision:1,enabled:true,source_kind:"predefined",cluster_id:null,
   validation:"source_only",source_file:"conf/env/one.yaml",display:{descriptor,base:"base_one"}},
  {id:"e2",name:"env_two",revision:1,enabled:true,source_kind:"predefined",cluster_id:null,
   validation:"source_only",source_file:"conf/env/two.yaml",display:{descriptor:{...descriptor,env_name:"env_two"},base:"base_two"}},
];
function mockApi(savedDrafts:unknown[] = []) {
  let revision = 0;
  vi.mocked(api).mockImplementation(async (path, method, payload) => {
    if (path === "/auth/me") return {id:"u1",username:"tester",email:"tester@example.com",role:"member",csrf_token:"token"};
    if (path === "/functional/options") return {digest,modules:{
      quota:[{path:"quota.yaml",id:"Q1",name:"配额用例",run_level:"daily",sha256:digest}],
      fault:[{path:"fault.yaml",id:"F1",name:"故障用例",run_level:"daily",sha256:digest}],
      client:[{path:"client.yaml",id:"C1",name:"客户端用例",run_level:"daily",sha256:digest}]},
      clusters:[{id:"c1",name:"主集群",machine:"control",management_machine:{id:"m1",name:"control",address:"10.0.0.1",ssh_user:"tester"},mds_addresses:["node:6900"],available:true}]};
    if (path === "/functional/environments") return profiles;
    if (path === "/functional/guided/metadata") return {enabled:true,clusters:[{id:"c1",name:"主集群",management_machine:{id:"m1",name:"control",address:"10.0.0.1",ssh_user:"tester"},mds_addresses:["node:6900"],available:true}],
      machines:[{id:"m1",name:"control",address:"10.0.0.1",ssh_user:"tester",aliases:[],available:true},
        {id:"m2",name:"客户端甲",address:"10.0.0.2",ssh_user:"tester",aliases:["node"],available:true}]};
    if ((path === "/functional/drafts" && method === "POST") ||
      (path === "/functional/drafts/draft-1" && method === "PUT")) {
      const data = payload as {name:string;step:number;configuration:unknown};
      revision += 1;
      return {id:"draft-1",revision,name:data.name,step:data.step,state:"draft",configuration:data.configuration};
    }
    if (path === "/functional/drafts") return savedDrafts;
    if (path.startsWith("/functional/drafts/")) return savedDrafts[0];
    if (path === "/functional/runs") return [{id:"completed",state:"success",name:"昨天的任务"}];
    if (path === "/functional/guided/compatibility" && method === "POST") {
      const data = payload as {module_plans:{module:string;environment_profile_id:string}[]};
      return {modules:Object.fromEntries(data.module_plans.map(plan => [plan.module,
        {compatible:plan.module !== "fault" || plan.environment_profile_id === "e2",
         reasons:plan.module === "fault" && plan.environment_profile_id !== "e2" ? ["缺少故障恢复能力"] : []}]))};
    }
    return {};
  });
}
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); vi.restoreAllMocks(); window.history.replaceState(null,"","#/"); });

test("test_new_start_does_not_restore_completed_run", async () => {
  window.history.replaceState(null,"","#/start/functional");
  mockApi();
  render(<App />);
  expect(await screen.findByRole("heading",{name:"选择测试环境"})).toBeInTheDocument();
  expect(screen.queryByText("昨天的任务")).not.toBeInTheDocument();
  expect(screen.getByLabelText("测试环境")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("测试环境"),{target:{value:"e1"}});
  expect(screen.getByText(/客户端甲（10\.0\.0\.2，tester/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/二进制路径/)).not.toBeInTheDocument();
  expect(screen.queryByText("创建文件系统")).not.toBeInTheDocument();
});

test("test_module_environment_required_when_incompatible", async () => {
  window.history.replaceState(null,"","#/start/functional");
  mockApi();
  render(<App />);
  fireEvent.change(await screen.findByLabelText("测试环境"),{target:{value:"e1"}});
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  expect(await screen.findByRole("heading",{name:"选择模块和用例"})).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("选择 quota 全部用例"));
  fireEvent.click(screen.getByLabelText("选择 fault 全部用例"));
  await waitFor(() => expect(screen.getByLabelText("fault 测试环境")).toHaveValue(""));
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("故障");
  fireEvent.change(screen.getByLabelText("fault 测试环境"),{target:{value:"e2"}});
  await waitFor(() => expect(screen.getByLabelText("fault 测试环境")).toHaveValue("e2"));
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  expect(await screen.findByRole("heading",{name:"运行设置"})).toBeInTheDocument();
});

test("applying one environment updates every other selected module", async () => {
  window.history.replaceState(null,"","#/start/functional");
  mockApi();
  render(<App />);
  fireEvent.change(await screen.findByLabelText("测试环境"),{target:{value:"e1"}});
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  await screen.findByRole("heading",{name:"选择模块和用例"});
  for (const module of ["quota","fault","client"])
    fireEvent.click(screen.getByLabelText(`选择 ${module} 全部用例`));
  fireEvent.change(screen.getByLabelText("fault 测试环境"),{target:{value:"e2"}});
  await waitFor(() => expect(screen.getAllByRole("button",{name:"将此环境应用到其他模块"})).toHaveLength(3));
  fireEvent.click(screen.getAllByRole("button",{name:"将此环境应用到其他模块"})[1]);
  expect(screen.getByLabelText("quota 测试环境")).toHaveValue("e2");
  expect(screen.getByLabelText("client 测试环境")).toHaveValue("e2");
});

test("test_defaults_1440_minutes_zero_retries", async () => {
  window.history.replaceState(null,"","#/start/functional");
  mockApi();
  render(<App />);
  fireEvent.change(await screen.findByLabelText("测试环境"),{target:{value:"e1"}});
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  fireEvent.click(await screen.findByLabelText("选择 quota 全部用例"));
  fireEvent.click(screen.getByRole("button",{name:"下一步"}));
  expect(await screen.findByRole("heading",{name:"运行设置"})).toBeInTheDocument();
  fireEvent.click(screen.getByText("高级选项"));
  expect(screen.getByLabelText("每个模块最长运行时间（分钟）")).toHaveValue(1440);
  expect(screen.getByLabelText("失败重试次数")).toHaveValue(0);
});

test("test_navigation_confirmation_before_leaving", async () => {
  window.history.replaceState(null,"","#/start/functional");
  mockApi();
  const confirm = vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<App />);
  expect(await screen.findByRole("heading",{name:"选择测试环境"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:/资源总览/}));
  expect(confirm).toHaveBeenCalledOnce();
  expect(window.location.hash).toBe("#/start/functional");
  fireEvent.click(screen.getByRole("button",{name:"返回开始页"}));
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(window.location.hash).toBe("#/start/functional");
});

test("case number search keeps the matching row without an empty warning", () => {
  render(<CaseSelector modules={{quota:[{path:"quota.yaml",id:"Q1",name:"配额用例"}]}} selected={{}} onChange={vi.fn()} />);
  fireEvent.change(screen.getByRole("searchbox",{name:"搜索用例"}),{target:{value:"Q1"}});
  expect(screen.getByText("配额用例")).toBeInTheDocument();
  expect(screen.queryByText("没有匹配用例，试试调整搜索条件。")).not.toBeInTheDocument();
});

test("preflight asks one explicit confirmation for the complete impact list", () => {
  render(<PreflightStep configuration={{kind:"existing-environments",version:2,cluster_id:"c1",
    default_environment_id:"e1",module_plans:[],name:"test",retries:0,timeout_minutes:1440}}
    profiles={profiles} metadata={{enabled:true,clusters:[]}} compatibility={null} busy={false}
    preflight={{can_start:true,token:"token",expires_at:null,checks:[],
      impacts:[{description:"影响客户端"},{description:"外部任务可能冲突"}],
      required_confirmations:["b".repeat(64),"a".repeat(64)]}}
    onCheck={vi.fn()} onInstall={vi.fn()} onStart={vi.fn()} />);
  expect(screen.getByText("影响客户端")).toBeInTheDocument();
  expect(screen.getByText("外部任务可能冲突")).toBeInTheDocument();
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.getByLabelText("我已阅读并确认以上影响范围")).toBeInTheDocument();
});

test("restoring a draft writes the explicit resume URL", async () => {
  window.history.replaceState(null,"","#/start/functional");
  const saved={id:"guided-draft",revision:2,name:"未完成测试",step:2,state:"draft",
    configuration:{kind:"existing-environments",version:2,cluster_id:"c1",default_environment_id:"e1",
      module_plans:[],name:"未完成测试",retries:0,timeout_minutes:1440}};
  mockApi([saved]);
  render(<App />);
  expect(await screen.findByText("恢复未提交草稿？")).toBeInTheDocument();
  expect(screen.getByRole("heading",{name:"选择测试环境"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"恢复此草稿"}));
  await waitFor(() => expect(window.location.hash).toBe("#/start/functional?draft=guided-draft"));
  expect(await screen.findByRole("heading",{name:"选择模块和用例"})).toBeInTheDocument();
});
