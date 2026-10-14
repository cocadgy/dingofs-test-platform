import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useState } from "react";
import { CacheProfilesPage } from "./CacheProfilesPage";
import { CacheProfileSelection } from "./CacheProfileSelection";
import { CacheParameterEditor } from "./CacheParameterEditor";
import { ResourceSectionForm } from "../resources/ResourceSectionForm";
import type { Execute } from "../resources/useResourceWorkspace";
import { sections } from "../resources/workspace";
import type { ResourceSnapshot } from "../resources/types";
import type { CacheCatalog, CacheOptions, CacheProfile } from "./types";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const catalog: CacheCatalog = {
  source_version: "test",
  fields: [
    {
      name: "shards",
      label: "分片数",
      type: "uint32",
      group: "运行时",
      description: "reactor shards",
      default: "8",
      managed: null,
      member_key: null,
    },
    {
      name: "cache_size_mb",
      label: "容量",
      type: "uint32",
      group: "缓存",
      description: "capacity",
      default: "102400",
      managed: null,
      member_key: "cache_size_mb",
    },
    {
      name: "id",
      label: "id",
      type: "string",
      group: "节点",
      description: "identity",
      default: null,
      managed: "平台生成 UUID",
      member_key: null,
    },
  ],
};
const profile: CacheProfile = {
  id: "p",
  name: "标准缓存",
  description: "常用配置",
  parameters: { shards: "4", cache_size_mb: "2048" },
  revision: 1,
  enabled: true,
  can_manage: true,
  creator_id: "u",
  source_version: "test",
  updated_at: "2026-10-10",
};

test("searches parameter descriptions, shows defaults, and resets explicit values", () => {
  function Editor() {
    const [v, setV] = useState<CacheOptions>({});
    return (
      <CacheParameterEditor catalog={catalog} values={v} onChange={setV} />
    );
  }
  render(<Editor />);
  expect(screen.getByLabelText("参数 --shards")).toBeDisabled();
  expect(screen.getByText("平台生成 UUID")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("自定义 --shards"));
  expect(screen.getByLabelText("参数 --shards")).toHaveValue("8");
  fireEvent.change(screen.getByLabelText("参数 --shards"), {
    target: { value: "16" },
  });
  fireEvent.change(screen.getByLabelText("搜索参数"), {
    target: { value: "reactor" },
  });
  expect(screen.queryByLabelText("自定义 --cache_size_mb")).toBeNull();
  fireEvent.click(screen.getByLabelText("自定义 --shards"));
  expect(screen.getByLabelText("参数 --shards")).toBeDisabled();
});

test("creates a named profile and saves only explicit options", async () => {
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path.endsWith("/catalog")) return catalog as never;
    if (method === "POST") return { ...profile, ...(body as object) } as never;
    return [] as never;
  });
  render(<CacheProfilesPage onDirty={vi.fn()} />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "新建缓存组配置" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "新建缓存组配置" }));
  fireEvent.change(screen.getByLabelText("配置名称"), {
    target: { value: "测试模板" },
  });
  fireEvent.click(screen.getByLabelText("自定义 --shards"));
  fireEvent.change(screen.getByLabelText("参数 --shards"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/cache-profiles",
      "POST",
      expect.objectContaining({
        name: "测试模板",
        parameters: { shards: "2" },
      }),
    ),
  );
});

test("other owners' profiles are read-only but can be copied", async () => {
  vi.mocked(api).mockImplementation(
    async (path) =>
      (path.endsWith("/catalog")
        ? catalog
        : [{ ...profile, can_manage: false }]) as never,
  );
  render(<CacheProfilesPage onDirty={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "标准缓存" }));
  expect(screen.queryByRole("button", { name: "保存配置" })).toBeNull();
  expect(screen.queryByRole("button", { name: "删除" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "复制" }));
  expect(screen.getByLabelText("配置名称")).toHaveValue("标准缓存 副本");
  expect(screen.getByRole("button", { name: "保存配置" })).not.toBeDisabled();
});

test("creation applies profile, allows temporary changes and new members inherit defaults", async () => {
  const execute = vi.fn<Execute>(async () => {});
  const action: ResourceSnapshot["catalog"][number] = {
    action: "cache.create",
    label: "创建缓存组",
    section: "cache",
    mutating: true,
    fields: [
      { key: "group_name", label: "缓存组名称", type: "text", default: "g" },
      { key: "cache_profile_id", label: "配置", type: "text", default: "" },
      {
        key: "cache_profile_revision",
        label: "版本",
        type: "number",
        default: 0,
      },
      {
        key: "cache_options",
        label: "参数",
        type: "cache_options",
        default: {},
      },
      { key: "members", label: "缓存成员", type: "members" },
    ],
  };
  const snapshot: ResourceSnapshot = {
    catalog: [action, { ...action, action: "cache.plan" }],
    cache_profiles: [profile],
    cache_parameter_catalog: catalog,
    resources: [],
    machines: [
      {
        id: "m",
        name: "node",
        address: "192.0.2.1",
        ssh_user: "root",
        can_manage: true,
      },
    ],
    operations: [],
  };
  render(
    <ResourceSectionForm
      section={sections[1]}
      group="缓存组操作"
      onGroupChange={vi.fn()}
      snapshot={snapshot}
      disabled={false}
      execute={execute}
    />,
  );
  fireEvent.change(screen.getByLabelText("缓存组配置"), {
    target: { value: "p" },
  });
  expect(screen.getByLabelText("成员 1 缓存容量 (MB)")).toHaveValue(2048);
  fireEvent.click(screen.getByText(/查看 \/ 修改本次启动参数/));
  fireEvent.change(screen.getByLabelText("参数 --shards"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加缓存成员" }));
  expect(screen.getByLabelText("成员 2 缓存容量 (MB)")).toHaveValue(2048);
  fireEvent.submit(
    screen.getByRole("button", { name: "检查并创建缓存组" }).closest("form")!,
  );
  await waitFor(() => expect(execute).toHaveBeenCalled());
  expect(execute.mock.calls[0][1]).toEqual(
    expect.objectContaining({
      cache_profile_id: "p",
      cache_profile_revision: 1,
      cache_options: { shards: "2", cache_size_mb: "2048" },
    }),
  );
  expect(profile.parameters.shards).toBe("4");
});

test("saves current cache options as a new profile without changing members", async () => {
  const onRefresh = vi.fn(), onChange = vi.fn();
  const originalMembers = [{cache_size_mb:4096,cache_dir:"/mnt/cache"}];
  function Selection() {
    const [values,setValues] = useState<Record<string,unknown>>({cache_options:{shards:"2"},members:originalMembers});
    const [profiles,setProfiles] = useState([profile]);
    return <CacheProfileSelection profiles={profiles} catalog={catalog}
      values={values} disabled={false} onRefresh={(rows,nextCatalog)=>{onRefresh(rows,nextCatalog);setProfiles(rows);}}
      onChange={patch=>{onChange(patch);setValues(previous=>({...previous,...patch}));}}/>;
  }
  const created={...profile,id:"new",name:"新缓存配置",revision:1,parameters:{shards:"2"}};
  vi.mocked(api).mockResolvedValue(created);
  render(<Selection/>);
  fireEvent.click(screen.getByText(/查看 \/ 修改本次启动参数/));
  fireEvent.change(screen.getByRole("textbox",{name:"新配置名称"}),{target:{value:"新缓存配置"}});
  fireEvent.click(screen.getByRole("button",{name:"保存到缓存组配置"}));
  await waitFor(()=>expect(api).toHaveBeenCalledWith("/cache-profiles","POST",{
    name:"新缓存配置",description:"",enabled:true,parameters:{shards:"2"},
  }));
  await waitFor(()=>expect(screen.getByRole("combobox",{name:"缓存组配置"})).toHaveValue("new"));
  expect(onChange).toHaveBeenCalledWith({cache_profile_id:"new",cache_profile_revision:1});
  expect(onChange.mock.calls.every(([patch])=>!Object.hasOwn(patch,"members"))).toBe(true);
  expect(originalMembers).toEqual([{cache_size_mb:4096,cache_dir:"/mnt/cache"}]);
});

test("cache profile save rejects duplicate names locally", () => {
  render(<CacheProfileSelection profiles={[profile]} catalog={catalog} values={{}} disabled={false} onRefresh={vi.fn()} onChange={vi.fn()}/>);
  fireEvent.click(screen.getByText(/查看 \/ 修改本次启动参数/));
  fireEvent.change(screen.getByRole("textbox",{name:"新配置名称"}),{target:{value:"标准缓存"}});
  fireEvent.click(screen.getByRole("button",{name:"保存到缓存组配置"}));
  expect(screen.getByRole("alert")).toHaveTextContent("名称已存在");
  expect(api).not.toHaveBeenCalled();
});
