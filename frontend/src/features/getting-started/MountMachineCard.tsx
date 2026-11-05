import { useState } from 'react';
import { GuidedCacheParameters } from './GuidedCacheParameters';
import { rdmaPairs } from '../resources/cacheRdma';
import type { ResourceMachine, SavedResource } from '../resources/types';
import type { CacheCatalog, CacheProfile } from '../cache-profiles/types';
import { mountPaths, type MountRow } from './guidedMountModel';
export function MountMachineCard({ row, machine, groups, pathMode, catalog, profiles, onChange, onSaved, onCopy }: {
  row: MountRow; machine: ResourceMachine; groups: SavedResource[]; pathMode: boolean; catalog?: CacheCatalog;
  profiles: CacheProfile[]; onChange: (patch: Partial<MountRow>) => void; onSaved: (profile: CacheProfile) => void; onCopy: () => void;
}) {
  const pairs = rdmaPairs(machine);
  const [copy, setCopy] = useState(false);
  const common = <div className="guided-cache-grid">
    <label>本地缓存目录<input value={row.options.cache_dir || ''} placeholder="留空由平台按客户端自动隔离" onChange={e => { const options = { ...row.options }; if (e.target.value) options.cache_dir = e.target.value; else delete options.cache_dir; onChange({ options }); }} /></label>
    <label>日志基础目录<input value={row.logDirectory} placeholder="留空由平台自动隔离" onChange={e => onChange({ logDirectory: e.target.value })} /></label>
    <label>缓存组<select value={row.cacheGroup} onChange={e => onChange({ cacheGroup: e.target.value })}><option value="">不使用缓存组</option>{groups.map(group => <option key={group.name} value={group.name} disabled={!Number(group.data.online_count)}>{group.name} · {Number(group.data.online_count) > 0 ? '在线 ' + group.data.online_count : '无在线成员'}</option>)}</select></label>
    <label>RDMA<select value={row.rdma ? 'on' : 'off'} onChange={e => onChange({ rdma: e.target.value === 'on' })}><option value="off">关闭</option><option value="on">开启</option></select></label>
    {row.rdma && <><label>RDMA 设备与端口<select value={row.rdmaDevice ? row.rdmaDevice + ':' + row.rdmaPort : ''} onChange={e => { const pair = pairs.find(p => p.device + ':' + p.port === e.target.value); onChange({ rdmaDevice: pair?.device || '', rdmaPort: pair?.port || 1 }); }}><option value="">请选择设备和端口</option>{pairs.map(p => <option key={p.device + ':' + p.port} value={p.device + ':' + p.port}>{p.device} · 端口 {p.port}</option>)}</select></label>{!pairs.length && <p className="error">该机器未采集可用的 RDMA 设备。</p>}</>}
  </div>;
  return <fieldset className="guided-cache-machine"><legend>{machine.name} · {machine.address}</legend>
    <div className="guided-cache-grid">
      <label>执行用户<input value={row.user} onChange={e => onChange({ user: e.target.value })} /></label>
      <label>客户端数量<input type="number" min="1" max="1000" value={row.count} onChange={e => onChange({ count: Number(e.target.value) })} /></label>
      <label>挂载路径<input value={row.mountPath} placeholder="/mnt/dingofs" onChange={e => onChange({ mountPath: e.target.value })} /></label>
      <label>挂载子目录<input value={row.subdir} onChange={e => onChange({ subdir: e.target.value })} /></label>
      {pathMode && <label>程序所在目录<input value={row.binaryDirectory} placeholder="/opt/dingofs/bin" onChange={e => onChange({ binaryDirectory: e.target.value })} /><small>使用本机已有 dingo-client，不下载或覆盖。</small></label>}
    </div>
    {row.mountPath && <details><summary>查看最终挂载路径（{row.count} 个）</summary>{mountPaths(row).map(path => <div key={path}><code>{path}</code></div>)}</details>}
    {catalog ? <GuidedCacheParameters tool="dingo-client" catalog={catalog} profiles={profiles} profileId={row.profileId} values={row.options} commonContent={common}
      onChange={options => onChange({ options })} onLoad={p => onChange(p ? { profileId: p.id, profileRevision: p.revision, options: { ...p.parameters } } : { profileId: '', profileRevision: 0 })}
      onSaved={p => { onSaved(p); onChange({ profileId: p.id, profileRevision: p.revision }); }} /> : common}
    {!copy ? <button onClick={() => setCopy(true)}>复制参数到其他已选机器</button> : <div role="alert"><p>覆盖其他机器通用参数，不复制身份、路径、端口及 RDMA 设备。是否继续？</p><button onClick={() => setCopy(false)}>取消</button><button onClick={() => { onCopy(); setCopy(false); }}>确认复制</button></div>}
  </fieldset>;
}
