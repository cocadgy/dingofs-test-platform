import {useState} from "react";
import {api} from "../../api/client";
import type {CacheCatalog,CacheProfile,CacheOptions} from "../cache-profiles/types";
import type {Parameters} from "../resources/types";
import {CacheParameterEditor} from "../cache-profiles/CacheParameterEditor";
export function MountProfileSelection({profiles:initialProfiles,catalog:initialCatalog,values,disabled,onChange}:{
  profiles:CacheProfile[];catalog:CacheCatalog;values:Parameters;disabled:boolean;onChange:(patch:Parameters)=>void;
}) {
  const [refreshed,setRefreshed]=useState<{profiles:CacheProfile[];catalog:CacheCatalog}>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const profiles=refreshed?.profiles || initialProfiles;
  const catalog=refreshed?.catalog || initialCatalog;
  async function refresh() {
    setBusy(true);setError("");
    try {
      const [profiles,catalog]=await Promise.all([api<CacheProfile[]>("/mount-profiles"),api<CacheCatalog>("/mount-profiles/catalog")]);
      setRefreshed({profiles,catalog});
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  const selected=profiles.find(p=>p.id===values.mount_profile_id);
  return <fieldset disabled={disabled || busy} className="resource-member"><legend>挂载配置</legend>
    <label>选择挂载配置<select value={String(values.mount_profile_id||"")} onChange={e=>{
      const p=profiles.find(row=>row.id===e.target.value);
      onChange({mount_profile_id:p?.id||"",mount_profile_revision:p?.revision||0,mount_options:{...p?.parameters}});
    }}><option value="">不使用模板 · 自定义本次参数</option>{profiles.filter(p=>p.enabled||p.id===selected?.id).map(p=><option key={p.id} value={p.id} disabled={!p.enabled}>{p.name}{!p.enabled?"（已停用）":""}</option>)}</select></label>
    <button type="button" onClick={()=>void refresh()}>刷新挂载配置</button>
    {error && <p role="alert">{error}</p>}
    {Boolean(values.mount_profile_id) && (!selected || !selected.enabled || selected.revision !== values.mount_profile_revision) && <p role="alert">所选配置已变化或不可用，请重新选择；提交时将再次校验。</p>}
    <a href="#/configuration/mount-profiles" target="_blank" rel="noreferrer">管理挂载配置</a>
    <p className="muted">本次修改只影响当前挂载，不修改保存的配置；文件系统、缓存组、挂载目录及 RDMA 在挂载表单设置。</p>
    <details><summary>调整本次挂载参数</summary><CacheParameterEditor tool="dingo-client" catalog={catalog} values={(values.mount_options as CacheOptions)||{}}
      onChange={mount_options=>onChange({mount_options})}/></details>
  </fieldset>;
}
