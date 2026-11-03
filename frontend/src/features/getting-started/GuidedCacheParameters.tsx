import { useState } from "react";
import { api } from "../../api/client";
import { CacheParameterEditor } from "../cache-profiles/CacheParameterEditor";
import type { CacheCatalog, CacheOptions, CacheProfile } from "../cache-profiles/types";

export function GuidedCacheParameters({ catalog, profiles, profileId, values, onChange, onLoad, onSaved }: {
  catalog: CacheCatalog; profiles: CacheProfile[]; profileId: string; values: CacheOptions;
  onChange: (values: CacheOptions) => void; onLoad: (profile?: CacheProfile) => void; onSaved: (profile: CacheProfile) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save() {
    if (busy || !name.trim()) return;
    if (profiles.some(p => p.name === name.trim())) { setMessage("模板名称已存在，请换一个名称。"); return; }
    setBusy(true); setMessage("");
    try {
      const allowed = new Set(catalog.fields.filter(f => !f.managed && f.name !== "id").map(f => f.name));
      const parameters = Object.fromEntries(Object.entries(values).filter(([key]) => allowed.has(key)));
      const saved = await api<CacheProfile>("/cache-profiles", "POST", { name: name.trim(), description: "", enabled: true, parameters });
      onSaved(saved); setName(""); setMessage("模板已保存；已有模板未被覆盖。");
    } catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="guided-cache-parameters">
    <label>加载已有模板<select value={profileId} disabled={busy} onChange={e => { onLoad(profiles.find(p => p.id === e.target.value)); setMessage(""); }}>
      <option value="">使用默认参数</option>
      {profiles.map(p => <option key={p.id} value={p.id} disabled={!p.enabled}>{p.name}</option>)}
    </select></label>
    <p className="muted">修改仅用于本次创建，不覆盖模板。容量、目录和 RDMA 在下一步按机器设置。</p>
    <CacheParameterEditor catalog={catalog} values={values} creation collapsible disabled={busy} onChange={onChange} />
    <div className="getting-started-actions"><label>新模板名称<input value={name} maxLength={120} disabled={busy} onChange={e => setName(e.target.value)} /></label><button disabled={busy || !name.trim()} onClick={() => void save()}>{busy ? "保存中…" : "另存为模板"}</button></div>
    {message && <p role="status">{message}</p>}
  </div>;
}
