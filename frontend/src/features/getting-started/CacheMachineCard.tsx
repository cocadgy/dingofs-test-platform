import { useState } from "react";
import { CapacityInput } from "./CapacityInput";
import { GuidedRdmaFields } from "./GuidedRdmaFields";
import { GuidedCacheParameters } from "./GuidedCacheParameters";
import { loadMachineTemplate, machineCacheOptions, type CacheMachineDraft } from "./guidedCacheModel";
import type { ResourceMachine } from "../resources/types";
import type { CacheCatalog, CacheProfile } from "../cache-profiles/types";

export function CacheMachineCard({ row, machine, pathMode, catalog, profiles, otherMachines, onChange, onSaved, onCopy }: {
  row: CacheMachineDraft; machine: ResourceMachine; pathMode: boolean; catalog?: CacheCatalog; profiles: CacheProfile[];
  otherMachines: ResourceMachine[]; onChange: (patch: Partial<CacheMachineDraft>) => void;
  onSaved: (profile: CacheProfile) => void; onCopy: (ids: string[]) => void;
}) {
  const [targets, setTargets] = useState<string[]>([]);
  const [confirmCopy, setConfirmCopy] = useState(false);
  const common = <div className="guided-cache-grid">
    <label>缓存基础目录<input value={row.directory} placeholder="/mnt/disk1/dingofs-cache" onChange={e => onChange({ directory: e.target.value })} /></label>
    <CapacityInput value={row.capacity} unit={row.capacityUnit} onChange={capacity => onChange({ capacity })} onUnitChange={capacityUnit => onChange({ capacityUnit })} />
    <label>一致性哈希权重<input type="number" min="0" max="4294967295" step="1" value={row.weight ?? Number(row.options?.group_weight ?? 100)} onChange={e => onChange({ weight: e.target.value === "" ? NaN : Number(e.target.value) })} /><small>本机所有缓存节点使用该权重，默认 100。</small></label>
    <label>RDMA<select value={row.rdma ? "on" : "off"} onChange={e => onChange({ rdma: e.target.value === "on" })}><option value="off">关闭</option><option value="on">开启</option></select></label>
    {row.rdma && <GuidedRdmaFields machine={machine} row={row} onChange={onChange} />}
  </div>;
  return <fieldset className="guided-cache-machine"><legend>{machine.name} · {machine.address}</legend>
    <div className="guided-cache-grid">
      <label>执行用户<input value={row.user} onChange={e => onChange({ user: e.target.value })} /></label>
      <label>节点数量<input type="number" min="1" value={row.count} onChange={e => onChange({ count: Number(e.target.value) })} /></label>
      <label>监听 IP<input value={row.listenIp} onChange={e => onChange({ listenIp: e.target.value })} /></label>
      <label>端口分配<select value={row.portMode} onChange={e => onChange({ portMode: e.target.value as "auto" | "manual" })}><option value="auto">自动分配</option><option value="manual">手动指定起始端口</option></select></label>
      {row.portMode === "manual" && <label>起始端口<input type="number" value={row.port} onChange={e => onChange({ port: Number(e.target.value) })} /></label>}
      {pathMode && <label>程序所在目录<input value={row.binaryDirectory} placeholder="/opt/dingofs/bin" onChange={e => onChange({ binaryDirectory: e.target.value })} /><small>使用本机该目录下已存在的 dingo-cache；平台不会下载或分发。</small></label>}
    </div>
    {catalog ? <GuidedCacheParameters catalog={catalog} profiles={profiles} profileId={row.profileId || ""} values={row.options || {}}
      saveValues={machineCacheOptions(row)} commonContent={common}
      onChange={options => onChange({ options })} onLoad={profile => onChange(loadMachineTemplate(row, profile))}
      onSaved={profile => { onSaved(profile); onChange({ profileId: profile.id, profileRevision: profile.revision }); }} />
      : <><p className="muted">正在读取完整参数…</p>{common}</>}
    {!!otherMachines.length && <details><summary>复制缓存参数到其他机器</summary>
      <p className="muted">只复制缓存参数，不复制机器地址、执行用户、节点数量、端口和程序目录。不会持续同步。</p>
      <div className="guided-cache-machines">{otherMachines.map(other => <label key={other.id}><input type="checkbox" checked={targets.includes(other.id)} onChange={e => { setTargets(current => e.target.checked ? [...current, other.id] : current.filter(id => id !== other.id)); setConfirmCopy(false); }} />{other.name} · {other.address}</label>)}</div>
      {!confirmCopy ? <button disabled={!targets.length} onClick={() => setConfirmCopy(true)}>复制参数</button> : <div role="alert">
        <p>将覆盖所选 {targets.length} 台机器当前填写的缓存参数，是否继续？</p>
        <button onClick={() => setConfirmCopy(false)}>取消</button><button onClick={() => { onCopy(targets); setConfirmCopy(false); setTargets([]); }}>确认覆盖</button>
      </div>}
    </details>}
  </fieldset>;
}
