import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { ClusterRow } from '../clusters/types';
import { DiscoverClusters } from '../clusters/DiscoverClusters';
import { StorageProfilesPage } from '../storage/StorageProfilesPage';
import { ResourceOperationView } from '../resources/ResourceOperationView';
import { pendingStates, type ResourceOperation, type ResourceSnapshot, type Parameters } from '../resources/types';
import { filesystemOptions } from '../resources/filesystemOptions';
import { cacheGroupResources } from '../resources/cacheGroupResources';
import { cacheRdmaReady } from '../resources/cacheRdma';
import { requestId } from '../resources/requestId';
import { CacheTagSelector } from './CacheTagSelector';
import { GuidedMachineForm } from './GuidedMachineForm';
import { GuidedFilesystemFlow } from './GuidedFilesystemFlow';
import { MountMachineCard } from './MountMachineCard';
import { blankMountDraft, buildMountClients, cloneMountSettings, mountPaths, newMountRow, type MountDraft, type MountRow } from './guidedMountModel';

type Props = { admin: boolean; userId?: string; route: string; onNavigate: (hash: string) => void; onDirty: (dirty: boolean) => void };
export function GuidedMountFlow({ admin, userId, route, onNavigate, onDirty }: Props) {
  const key = 'guided-mount-draft-' + (userId || '');
  const [draft, setDraft] = useState<MountDraft>(() => {
    try { const saved = JSON.parse(sessionStorage.getItem(key) || 'null'); return saved && Array.isArray(saved.rows) ? { ...blankMountDraft(), ...saved } : blankMountDraft(); }
    catch { return blankMountDraft(); }
  });
  const [step, setStep] = useState(1);
  const [clusters, setClusters] = useState<ClusterRow[]>([]);
  const [snapshot, setSnapshot] = useState<ResourceSnapshot>();
  const [operation, setOperation] = useState<ResourceOperation>();
  const [query, setQuery] = useState<ResourceOperation>();
  const [fsQuery, setFsQuery] = useState<ResourceOperation>();
  const [cacheQuery, setCacheQuery] = useState<ResourceOperation>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const live = useRef(true), sending = useRef(false);
  const version = useRef(0), completedQuery = useRef(''), startedPlan = useRef('');
  const newMachine = useRef('');
  const cluster = clusters.find(c => c.id === draft.clusterId);
  const machines = (snapshot?.machines || []).filter(m => m.can_manage);
  const profiles = (snapshot?.mount_profiles || []).filter(p => p.enabled);
  const active = busy || !!operation && pendingStates.includes(operation.state) || !!query && pendingStates.includes(query.state);
  let filesystems: string[] = [], groups: ReturnType<typeof cacheGroupResources> = [];
  try { if (fsQuery?.state === 'succeeded') filesystems = filesystemOptions(fsQuery).map(f => f.name); } catch { /* failed parsing blocks Next */ }
  try { if (cacheQuery?.state === 'succeeded') groups = cacheGroupResources(cacheQuery, snapshot?.resources || []); } catch { /* refresh remains available */ }
  const update = (patch: Partial<MountDraft>) => { setDraft(d => ({ ...d, ...patch })); setError(''); };
  const rowUpdate = (id: string, patch: Partial<MountRow>) => setDraft(d => ({ ...d, rows: d.rows.map(r => r.machineId === id ? { ...r, ...patch } : r) }));
  const back = () => onNavigate('#/start/mount');
  useEffect(() => { live.current = true; return () => { live.current = false; onDirty(false); }; }, [onDirty]);
  useEffect(() => { sessionStorage.setItem(key, JSON.stringify(draft)); onDirty(!!draft.clusterId || draft.rows.length > 0 || active); }, [key, draft, active, onDirty]);
  useEffect(() => {
    let current = true;
    (async () => {
      try {
        const rows: ClusterRow[] = [];
        for (let offset = 0; ;) {
          const page = await api<{ items: ClusterRow[]; total: number }>('/clusters/overview?limit=200&offset=' + offset);
          rows.push(...page.items); offset += page.items.length;
          if (!page.items.length || offset >= page.total) break;
        }
        if (current) setClusters(rows.filter(c => !c.archived && c.binding_state === 'verified' && (admin || c.creator_id === userId)));
      } catch (e) { if (current) setError((e as Error).message); }
    })();
    return () => { current = false; };
  }, [route, admin, userId]);
  const loadSnapshot = useCallback(async () => {
    if (!draft.clusterId) return;
    const sequence = ++version.current;
    try {
      const result = await api<ResourceSnapshot>('/clusters/' + encodeURIComponent(draft.clusterId) + '/resources');
      if (!live.current || sequence !== version.current) return;
      setSnapshot(result);
      const machine = result.machines.find(m => m.id === newMachine.current && m.can_manage);
      if (machine) { setDraft(d => ({ ...d, rows: d.rows.some(r => r.machineId === machine.id) ? d.rows : [...d.rows, d.rows.length ? cloneMountSettings(d.rows[0], newMountRow(machine)) : newMountRow(machine)] })); newMachine.current = ''; }
    } catch (e) { if (live.current && sequence === version.current) setError((e as Error).message); }
  }, [draft.clusterId]);
  useEffect(() => { setSnapshot(undefined); setFsQuery(undefined); setCacheQuery(undefined); setQuery(undefined); void loadSnapshot(); }, [loadSnapshot]);
  useEffect(() => { if (route === '#/start/mount') void loadSnapshot(); }, [route, loadSnapshot]);
  useEffect(() => {
    const id = sessionStorage.getItem(key + '-operation');
    if (!id) return;
    let current = true;
    api<ResourceOperation>('/resource-operations/' + encodeURIComponent(id)).then(op => { if (current) { setOperation(op); setStep(5); } }).catch(e => { if (current) setError('读取上次任务失败：' + e.message); });
    return () => { current = false; };
  }, [key]);
  async function queryList(action: 'fs.list' | 'cache.list') {
    if (!cluster || sending.current) return;
    sending.current = true; setBusy(true); setError('');
    const sequence = version.current;
    try {
      const next = await api<ResourceOperation>('/clusters/' + encodeURIComponent(cluster.id) + '/resource-operations', 'POST', {
        action, parameters: {}, base_revision: cluster.revision, request_id: requestId(), confirmed: false,
      });
      if (live.current && sequence === version.current) setQuery(next);
    } catch (e) { if (live.current) setError((e as Error).message); }
    finally { sending.current = false; if (live.current) setBusy(false); }
  }
  useEffect(() => {
    if (!query || pendingStates.includes(query.state) || completedQuery.current === query.id + query.state) return;
    completedQuery.current = query.id + query.state;
    if (query.action === 'fs.list') setFsQuery(query); else setCacheQuery(query);
    if (query.state !== 'succeeded') setError(query.message || '列表查询失败，请重新获取');
  }, [query]);
  const initialQuery = useRef('');
  useEffect(() => {
    if (!cluster || !snapshot || active || initialQuery.current === cluster.id || operation) return;
    initialQuery.current = cluster.id;
    void queryList('fs.list');
  }, [cluster, snapshot, active, operation]);
  async function submit(action: 'mount.plan' | 'mount.create', parameters: Parameters) {
    if (!cluster || sending.current) return;
    sending.current = true; setBusy(true); setError('');
    const fingerprint = JSON.stringify({ cluster: cluster.id, revision: cluster.revision, action, parameters });
    let saved: { fingerprint: string; id: string } | undefined;
    try { saved = JSON.parse(sessionStorage.getItem(key + '-request') || 'null'); } catch { /* new request */ }
    const id = saved?.fingerprint === fingerprint ? saved.id : requestId();
    sessionStorage.setItem(key + '-request', JSON.stringify({ fingerprint, id }));
    try {
      const next = await api<ResourceOperation>('/clusters/' + encodeURIComponent(cluster.id) + '/resource-operations', 'POST', {
        action, parameters, base_revision: cluster.revision, request_id: id, confirmed: true,
      });
      if (live.current) { sessionStorage.setItem(key + '-operation', next.id); setOperation(next); setStep(5); }
    } catch (e) { if (live.current) setError((e as Error).message + '。请重试同一提交以查询结果，不要另建任务。'); }
    finally { sending.current = false; if (live.current) setBusy(false); }
  }
  useEffect(() => {
    if (operation?.action !== 'mount.plan' || operation.state !== 'succeeded' || !cluster || busy || startedPlan.current === operation.id) return;
    startedPlan.current = operation.id;
    void submit('mount.create', { plan_id: operation.id });
  }, [operation, cluster, busy]);
  function checkDraft() {
    try {
      const clients = buildMountClients(draft);
      if (draft.rows.some(r => !machines.some(m => m.id === r.machineId))) throw new Error('机器已不可用，请重新选择');
      if (!cacheRdmaReady(clients, machines)) throw new Error('RDMA 设备或端口不属于当前机器');
      if (draft.rows.some(r => r.profileId && !profiles.some(p => p.id === r.profileId && p.revision === r.profileRevision))) throw new Error('参数模板已变化，请重新加载');
      if (draft.rows.some(r => r.cacheGroup && !groups.some(g => g.name === r.cacheGroup && Number(g.data.online_count) > 0))) throw new Error('缓存组没有在线成员，请重新获取列表');
      setError(''); return clients;
    } catch (e) { setError((e as Error).message); return undefined; }
  }
  if (route.endsWith('/machine')) return <section className="getting-started"><h1>添加机器</h1><GuidedMachineForm onDirty={onDirty} onBack={back} continueLabel="继续挂载文件系统" onCreated={id => { newMachine.current = id; onNavigate(route.includes('/cluster/') ? '#/start/mount/cluster' : '#/start/mount'); }} /></section>;
  if (route === '#/start/mount/cluster') return <section className="getting-started"><h1>添加集群</h1><DiscoverClusters guided admin={admin} userId={userId} initialMachineId={newMachine.current || undefined} onAddMachine={() => onNavigate('#/start/mount/cluster/machine')} onClose={back} onImported={ids => { update({ clusterId: ids[0], fsName: '', rows: [] }); setStep(1); back(); }} /></section>;
  if (route === '#/start/mount/filesystem/storage') return <section className="getting-started"><h1>添加存储配置</h1><button onClick={() => onNavigate('#/start/mount/filesystem')}>返回创建文件系统</button><StorageProfilesPage onDirty={onDirty} onCreated={id => { const saved = JSON.parse(sessionStorage.getItem('guided-filesystem-draft') || '{}'); sessionStorage.setItem('guided-filesystem-draft', JSON.stringify({ ...saved, storageId: id })); sessionStorage.setItem('guided-filesystem-storage-return', '1'); onNavigate('#/start/mount/filesystem'); }} /></section>;
  if (route === '#/start/mount/filesystem') return <section className="getting-started"><h1>创建文件系统</h1><button onClick={back}>返回挂载引导</button><GuidedFilesystemFlow admin={admin} userId={userId} onDirty={onDirty} onNavigate={hash => onNavigate(hash.replace('#/start/filesystem', '#/start/mount/filesystem').replace('#/start/cluster', '#/start/mount/cluster'))} onCreated={(clusterId, fsName) => { update({ clusterId, fsName }); initialQuery.current = ''; setStep(1); back(); }} /></section>;
  return <section className="getting-started guided-cache-flow"><p className="eyebrow">GETTING STARTED / MOUNT</p><h1>挂载文件系统</h1><section className="getting-started-card">
    <p className="muted">{step < 5 ? `步骤 ${step} / 4` : '执行结果'}</p>
    {error && <p role="alert" className="error">{error}</p>}
    {step === 1 && <><h2>选择集群和文件系统</h2><label>目标集群<select disabled={active} value={draft.clusterId} onChange={e => { initialQuery.current = ''; update({ clusterId: e.target.value, fsName: '', rows: [] }); }}><option value="">请选择集群</option>{clusters.map(c => <option key={c.id} value={c.id}>{c.external_name} · {c.machine_name} ({c.machine_address}) · {c.os_user}</option>)}</select></label>
      <label>文件系统<select disabled={active} value={draft.fsName} onChange={e => update({ fsName: e.target.value })}><option value="">请选择文件系统</option>{filesystems.map(name => <option key={name}>{name}</option>)}</select></label>
      <div className="getting-started-actions"><button disabled={active} onClick={() => onNavigate('#/start/mount/cluster')}>先添加集群</button><button disabled={active || !cluster} onClick={() => { sessionStorage.setItem('guided-filesystem-draft', JSON.stringify({ clusterId: draft.clusterId, fsName: '', storageId: '', suffix: 'none', partition: 'hash' })); onNavigate('#/start/mount/filesystem'); }}>先创建文件系统</button><button disabled={active || !cluster} onClick={() => void queryList('fs.list')}>重新获取文件系统</button><button className="primary" disabled={active || !filesystems.includes(draft.fsName)} onClick={() => setStep(2)}>下一步</button></div></>}
    {step === 2 && <><h2>选择客户端程序来源</h2><label>程序来源<select value={draft.source} onChange={e => update({ source: e.target.value as MountDraft['source'] })}><option value="default">使用机器默认 dingo-client</option><option value="tag">使用指定 TAG</option><option value="path">使用目标机器已有程序</option></select></label>{draft.source === 'tag' && <CacheTagSelector tag={draft.tag} digest={draft.digest} onChange={(tag, digest) => update({ tag, digest })} />}{draft.source === 'path' && <p>下一步逐台填写已有 dingo-client 所在目录，不下载或覆盖。</p>}<div className="getting-started-actions"><button onClick={() => setStep(1)}>上一步</button><button className="primary" disabled={active || draft.source === 'tag' && !draft.digest} onClick={() => { setStep(3); if (!cacheQuery) void queryList('cache.list'); }}>下一步</button></div></>}
    {step === 3 && <><h2>选择挂载机器并配置参数</h2><p>新增机器继承第一台的通用参数；路径、执行用户、程序目录和 RDMA 设备逐台确认。</p><div className="guided-cache-machines">{machines.map(machine => <label key={machine.id}><input type="checkbox" disabled={active} checked={draft.rows.some(r => r.machineId === machine.id)} onChange={e => update({ rows: e.target.checked ? [...draft.rows, draft.rows.length ? cloneMountSettings(draft.rows[0], newMountRow(machine)) : newMountRow(machine)] : draft.rows.filter(r => r.machineId !== machine.id) })} />{machine.name} · {machine.address}</label>)}</div><div className="getting-started-actions"><button disabled={active} onClick={() => onNavigate('#/start/mount/machine')}>先添加机器</button><button disabled={active} onClick={() => void queryList('cache.list')}>重新获取缓存组</button></div>
      {draft.rows.map(row => { const machine = machines.find(m => m.id === row.machineId); return machine ? <MountMachineCard key={row.machineId} row={row} machine={machine} groups={groups} pathMode={draft.source === 'path'} catalog={snapshot?.mount_parameter_catalog} profiles={profiles} onChange={patch => rowUpdate(row.machineId, patch)} onSaved={p => setSnapshot(s => s ? { ...s, mount_profiles: [...(s.mount_profiles || []).filter(old => old.id !== p.id), p] } : s)} onCopy={() => setDraft(d => ({ ...d, rows: d.rows.map(other => other.machineId === row.machineId ? other : cloneMountSettings(row, other)) }))} /> : <p key={row.machineId} className="error">原机器已不可用，请重新选择。</p>; })}
      <div className="getting-started-actions"><button disabled={active} onClick={() => setStep(2)}>上一步</button><button className="primary" disabled={active || !draft.rows.length} onClick={() => { if (checkDraft()) setStep(4); }}>下一步</button></div></>}
    {step === 4 && <><h2>确认并检查挂载</h2><p>文件系统：{draft.fsName}；程序来源：{draft.source === 'tag' ? 'TAG ' + draft.tag : draft.source === 'path' ? '目标机器已有程序' : '各机器默认程序'}</p><p>检查通过后自动挂载，不覆盖已有挂载或非空目录。</p>{draft.rows.map(row => <details key={row.machineId} open><summary>{machines.find(m => m.id === row.machineId)?.name} · {machines.find(m => m.id === row.machineId)?.address} · {row.user} · {row.count} 个客户端</summary>{mountPaths(row).map(path => <div key={path}><code>{path}</code></div>)}<pre>{JSON.stringify(buildMountClients({ ...draft, rows: [row] })[0], null, 2)}</pre></details>)}<div className="getting-started-actions"><button disabled={active} onClick={() => setStep(3)}>上一步</button><button className="primary" disabled={active} onClick={() => { const clients = checkDraft(); if (clients) void submit('mount.plan', { fs_name: draft.fsName, clients }); }}>检查并挂载</button></div></>}
    {query && step < 5 && <ResourceOperationView operation={query} label="获取集群资源" canManage onChange={setQuery} />}
    {step === 5 && operation && <><h2>{operation.action === 'mount.create' && operation.state === 'succeeded' ? '挂载完成' : '挂载任务'}</h2><ResourceOperationView operation={operation} label={operation.action === 'mount.plan' ? '检查挂载计划' : '挂载文件系统'} canManage onChange={setOperation} />
      <div className="getting-started-actions">{operation.action === 'mount.plan' && operation.state === 'succeeded' && <button disabled={active} onClick={() => void submit('mount.create', { plan_id: operation.id })}>继续挂载</button>}{operation.action === 'mount.create' && ['failed', 'cancelled', 'interrupted', 'unknown'].includes(operation.state) && <button disabled={active} onClick={() => void submit('mount.create', { retry_operation_id: operation.id })}>重试未成功客户端</button>}<button disabled={active} onClick={() => onNavigate('#/clusters/' + draft.clusterId + '/resources')}>查看挂载点</button>{!active && <button onClick={() => { sessionStorage.removeItem(key + '-operation'); sessionStorage.removeItem(key + '-request'); setOperation(undefined); setStep(3); }}>返回配置</button>}</div></>}
  </section></section>;
}
