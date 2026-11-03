import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GuidedCacheParameters } from "./GuidedCacheParameters";
import type { CacheCatalog, CacheOptions, CacheProfile } from "../cache-profiles/types";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); });
const catalog: CacheCatalog = { source_version: "test", fields: [
  { name: "cache_expire_s", label: "过期时间", type: "uint64", group: "cache", default: "0", managed: null, member_key: null, description: "expiration" },
  { name: "rare_option", label: "其他设置", type: "string", group: "other", default: "", managed: null, member_key: null, description: "rare" },
  { name: "id", label: "节点ID", type: "string", group: "cache", default: "", managed: "自动生成", member_key: null, description: "id" },
] };
const profile = { id: "p", name: "已有模板", parameters: { cache_expire_s: "60" }, enabled: true, revision: 1, description: "", creator_id: "u", source_version: "test", can_manage: true, updated_at: "2026-11-03T00:00:00Z" } satisfies CacheProfile;
function Form() {
  const [values, setValues] = useState<CacheOptions>({});
  const [profileId, setProfileId] = useState("");
  return <GuidedCacheParameters catalog={catalog} profiles={[profile]} profileId={profileId} values={values}
    onChange={setValues} onLoad={p => { setProfileId(p?.id || ""); if (p) setValues({ ...p.parameters }); }} onSaved={p => setProfileId(p.id)} />;
}
test("common parameters open, other parameters collapsed, loading then saving uses edited values", async () => {
  vi.mocked(api).mockResolvedValue({ ...profile, id: "new", name: "新模板" });
  render(<Form />);
  expect(screen.getByText("常用参数", { selector: "summary" }).closest("details")).toHaveAttribute("open");
  expect(screen.getByText(/其他参数（/).closest("details")).not.toHaveAttribute("open");
  fireEvent.change(screen.getByLabelText("加载已有模板"), { target: { value: "p" } });
  expect(screen.getByLabelText("参数 --cache_expire_s")).toHaveValue("60");
  fireEvent.change(screen.getByLabelText("参数 --cache_expire_s"), { target: { value: "90" } });
  fireEvent.change(screen.getByLabelText("新模板名称"), { target: { value: "新模板" } });
  fireEvent.click(screen.getByRole("button", { name: "另存为模板" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/cache-profiles", "POST", expect.objectContaining({ name: "新模板", parameters: { cache_expire_s: "90" } })));
  expect(profile.parameters.cache_expire_s).toBe("60");
});

test("detaching a template preserves the current filled parameters", () => {
  render(<Form />);
  fireEvent.change(screen.getByLabelText("加载已有模板"), { target: { value: "p" } });
  fireEvent.change(screen.getByLabelText("参数 --cache_expire_s"), { target: { value: "90" } });
  fireEvent.change(screen.getByLabelText("加载已有模板"), { target: { value: "" } });
  expect(screen.getByRole("option", { name: "使用当前填写的参数" })).toBeInTheDocument();
  expect(screen.getByLabelText("参数 --cache_expire_s")).toHaveValue("90");
});

test("unavailable template remains visibly selected so current parameters can be kept", () => {
  const onLoad = vi.fn();
  render(<GuidedCacheParameters catalog={catalog} profiles={[]} profileId="deleted"
    values={{cache_expire_s:"90"}} onChange={vi.fn()} onLoad={onLoad} onSaved={vi.fn()} />);
  expect(screen.getByLabelText("加载已有模板")).toHaveValue("deleted");
  expect(screen.getByRole("option", {name:"原模板已不可用（保留当前参数）"})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("加载已有模板"), {target:{value:""}});
  expect(onLoad).toHaveBeenCalledWith(undefined);
  expect(screen.getByLabelText("参数 --cache_expire_s")).toHaveValue("90");
});
