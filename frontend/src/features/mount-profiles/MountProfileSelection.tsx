import { useState } from "react";
import { api } from "../../api/client";
import type { CacheCatalog, CacheProfile, CacheOptions } from "../cache-profiles/types";
import type { Parameters } from "../resources/types";
import { CacheParameterEditor } from "../cache-profiles/CacheParameterEditor";

export function MountProfileSelection({ profiles: initialProfiles, catalog: initialCatalog, values, disabled, onChange }: {
  profiles: CacheProfile[]; catalog: CacheCatalog; values: Parameters; disabled: boolean; onChange: (patch: Parameters) => void;
}) {
  const [refreshed, setRefreshed] = useState<{ profiles: CacheProfile[]; catalog: CacheCatalog }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newName, setNewName] = useState("");
  const profiles = refreshed?.profiles || initialProfiles;
  const catalog = refreshed?.catalog || initialCatalog;
  const selected = profiles.find(p => p.id === values.mount_profile_id);

  async function refresh() {
    setBusy(true); setError(""); setNotice("");
    try {
      const [rows, nextCatalog] = await Promise.all([
        api<CacheProfile[]>("/mount-profiles"), api<CacheCatalog>("/mount-profiles/catalog"),
      ]);
      setRefreshed({ profiles: rows, catalog: nextCatalog });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function saveCurrent() {
    const name = newName.trim();
    if (!name || disabled || busy) return;
    setError(""); setNotice("");
    if (profiles.some(profile => profile.name === name)) {
      setError("配置名称已存在，请使用其他名称。");
      return;
    }
    setBusy(true);
    try {
      const parameters = { ...((values.mount_options as CacheOptions) || {}) };
      const row = await api<CacheProfile>("/mount-profiles", "POST", {
        name, description: "", enabled: true, parameters,
      });
      setRefreshed(previous => ({
        catalog: previous?.catalog || catalog,
        profiles: [...(previous?.profiles || profiles).filter(profile => profile.id !== row.id), row]
          .sort((left, right) => left.name.localeCompare(right.name)),
      }));
      onChange({ mount_profile_id: row.id, mount_profile_revision: row.revision });
      setNewName("");
      setNotice(`已保存并选中挂载配置“${row.name}”。`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <fieldset disabled={disabled || busy} className="resource-member"><legend>挂载配置</legend>
    <label>选择挂载配置<select value={String(values.mount_profile_id || "")} onChange={e => {
      const profile = profiles.find(row => row.id === e.target.value);
      onChange({ mount_profile_id: profile?.id || "", mount_profile_revision: profile?.revision || 0, mount_options: { ...profile?.parameters } });
      setNotice("");
    }}><option value="">不使用模板 · 自定义本次参数</option>{profiles.filter(profile => profile.enabled || profile.id === selected?.id).map(profile => <option key={profile.id} value={profile.id} disabled={!profile.enabled}>{profile.name}{!profile.enabled ? "（已停用）" : ""}</option>)}</select></label>
    <button type="button" onClick={() => void refresh()}>刷新挂载配置</button>
    {Boolean(values.mount_profile_id) && (!selected || !selected.enabled || selected.revision !== values.mount_profile_revision) && <p role="alert">所选配置已变化或不可用，请重新选择；提交时将再次校验。</p>}
    <a href="#/configuration/mount-profiles" target="_blank" rel="noreferrer">管理挂载配置</a>
    <p className="muted">本次修改只影响当前挂载，不修改保存的配置；文件系统、缓存组、挂载目录及 RDMA 在挂载表单设置。</p>
    <details><summary>调整本次挂载参数</summary>
      <CacheParameterEditor tool="dingo-client" catalog={catalog} values={(values.mount_options as CacheOptions) || {}}
        onChange={mount_options => { onChange({ mount_options }); setNotice(""); }} />
      <div className="cache-profile-toolbar">
        <label>新配置名称<input value={newName} maxLength={120} onChange={e => setNewName(e.target.value)} placeholder="输入名称以保存当前参数" /></label>
        <button type="button" disabled={!newName.trim()} onClick={() => void saveCurrent()}>保存到挂载配置</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </details>
  </fieldset>;
}
