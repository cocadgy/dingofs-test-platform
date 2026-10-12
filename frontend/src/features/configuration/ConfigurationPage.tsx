import {useCallback,useState} from "react";
import {StorageProfilesPage} from "../storage/StorageProfilesPage";
import {CacheProfilesPage} from "../cache-profiles/CacheProfilesPage";
import {MountProfilesPage} from "../mount-profiles/MountProfilesPage";
export function ConfigurationPage({onDirty}: {onDirty:(dirty:boolean)=>void}) {
  const [dirty,setDirty]=useState(false);
  const handleDirty=useCallback((value:boolean)=>{setDirty(value);onDirty(value);},[onDirty]);
  const hash=window.location.hash;
  const tab=hash.includes("cache-profiles") ? "cache-profiles" : hash.includes("mount-profiles") ? "mount-profiles" : "storage";
  return <section><h1>配置管理</h1><nav className="actions" aria-label="配置分类">
    {[["storage","存储配置"],["cache-profiles","缓存组配置"],["mount-profiles","挂载配置"]].map(([key,label]) =>
      <button key={key} aria-current={tab===key ? "page":undefined} onClick={() => {
        if (tab===key || (dirty && !confirm("有未保存修改，确定离开？"))) return;
        setDirty(false);onDirty(false);window.location.hash=`#/configuration/${key}`;
      }}>{label}</button>)}
  </nav><ConfigurationContent key={tab} tab={tab} onDirty={handleDirty} /></section>;
}
function ConfigurationContent({tab,onDirty}:{tab:string;onDirty:(dirty:boolean)=>void}) {
  return tab==="cache-profiles" ? <CacheProfilesPage onDirty={onDirty}/> : tab==="mount-profiles" ? <MountProfilesPage onDirty={onDirty}/> : <StorageProfilesPage onDirty={onDirty}/>;
}
