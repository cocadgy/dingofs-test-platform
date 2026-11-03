import { guidedRdmaError } from "./GuidedRdmaFields";
import { capacityFactors } from "./CapacityInput";
import { CacheMachineCard } from "./CacheMachineCard";
import { CacheTagSelector } from "./CacheTagSelector";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ClusterRow } from "../clusters/types";
import { DiscoverClusters } from "../clusters/DiscoverClusters";
import { CacheProfilesPage } from "../cache-profiles/CacheProfilesPage";
import { GuidedMachineForm } from "./GuidedMachineForm";
import { ResourceOperationView } from "../resources/ResourceOperationView";
import { requestId } from "../resources/requestId";
import { pendingStates, type ResourceOperation, type ResourceSnapshot, type Parameters } from "../resources/types";
import { formatFilesystemName, type FilesystemSuffix } from "./filesystemName";
import { blankCacheDraft, cacheDraftError, cacheMembers, newCacheRow, cloneCacheSettings, migrateCacheDraft, machineCacheOptions, type CacheDraft, type CacheMachineDraft } from "./guidedCacheModel";

type Operation = ResourceOperation & { resource_id?: string };
type Props = { admin: boolean; userId?: string; route: string; onNavigate: (hash: string) => void; onDirty: (dirty: boolean) => void };
export function GuidedCacheFlow({ admin, userId, route, onNavigate, onDirty }: Props) {
  const key = "guided-cache-draft-" + (userId || "");
  const operationKey = key + "-operation";
  const [draft, setDraft] = useState<CacheDraft>(() => {
    try { const saved = JSON.parse(sessionStorage.getItem(key) || "null"); return saved && Array.isArray(saved.rows) ? { ...blankCacheDraft(), ...saved, ...(saved.source === "commit" ? { source: "tag", tag: "", imageDigest: "" } : {}) } : blankCacheDraft(); }
    catch { return blankCacheDraft(); }
  });
  const [step, setStep] = useState(1);
  const [clusters, setClusters] = useState<ClusterRow[]>([]);
  const [snapshot, setSnapshot] = useState<ResourceSnapshot>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [finalName, setFinalName] = useState("");
  const [operation, setOperation] = useState<Operation>();
  const [plan, setPlan] = useState<Operation>();
  const submittedPlan = useRef("");
  const sending = useRef(false);
  const newMachine = useRef("");
  const alive = useRef(true);
  const cluster = clusters.find(item => item.id === draft.clusterId);
  const machines = (snapshot?.machines || []).filter(item => item.can_manage);
  const profiles = (snapshot?.cache_profiles || []).filter(item => item.enabled);
  const active = !!operation && pendingStates.includes(operation.state);
  const sourceText = draft.source === "default" ? "机器默认程序" : draft.source === "tag" ? "TAG " + draft.tag : "使用目标机器已有程序（目录逐台指定）";
  const count = draft.rows.reduce((sum, row) => sum + row.count, 0);
  const capacity = draft.rows.reduce((sum, row) => sum + row.count * row.capacity, 0);
  const loadSnapshot = useCallback(async () => {
    if (!draft.clusterId) return;
    try {
      const next = await api<ResourceSnapshot>("/clusters/" + encodeURIComponent(draft.clusterId) + "/resources");
      if (!alive.current) return;
      setSnapshot(next);
      setDraft(current => migrateCacheDraft(current, next.cache_profiles || []));
      if (newMachine.current) {
        const machine = next.machines.find(item => item.id === newMachine.current);
        if (machine) setDraft(current => ({ ...current, rows: current.rows.some(row => row.machineId === machine.id) ? current.rows : [...current.rows, current.rows.length ? cloneCacheSettings(current.rows[0], newCacheRow(machine), machine) : newCacheRow(machine)] }));
        newMachine.current = "";
      }
    } catch (cause) { if (alive.current) setError((cause as Error).message); }
  }, [draft.clusterId]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; onDirty(false); }; }, [onDirty]);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const all: ClusterRow[] = [];
        for (let offset = 0; ;) {
          const page = await api<{ items: ClusterRow[]; total: number }>("/clusters/overview?limit=200&offset=" + offset);
          all.push(...page.items); offset += page.items.length;
          if (!page.items.length || offset >= page.total) break;
        }
        if (live) setClusters(all.filter(item => !item.archived && item.binding_state === "verified" && (admin || item.creator_id === userId)));
      } catch (cause) { if (live) setError((cause as Error).message); }
    })();
    return () => { live = false; };
  }, [admin, userId, route]);
  useEffect(() => { setSnapshot(undefined); void loadSnapshot(); }, [loadSnapshot, route]);
  useEffect(() => { sessionStorage.setItem(key, JSON.stringify(draft)); onDirty(!!draft.clusterId || !!draft.name || active); }, [key, draft, active, onDirty]);
  useEffect(() => {
    const id = sessionStorage.getItem(operationKey);
    if (id) api<Operation>("/resource-operations/" + encodeURIComponent(id)).then(value => {
      if (alive.current) { setOperation(value); if (value.action === "cache.plan") setPlan(value); setStep(5); }
    }).catch(cause => { if (alive.current) setError("读取上次任务失败：" + cause.message); });
  }, [operationKey]);
  useEffect(() => {
    if (operation) { sessionStorage.setItem(operationKey, operation.id); void loadSnapshot(); }
  }, [operation?.id, operation?.state, operationKey, loadSnapshot]);
  const startFromPlan = useCallback(async (checked: Operation) => {
    if (!cluster || sending.current) return;
    sending.current = true; setBusy(true); setError("");
    try {
      const next = await api<Operation>("/clusters/" + encodeURIComponent(cluster.id) + "/resource-operations", "POST", {
        action: "cache.create", base_revision: cluster.revision, request_id: checked.id, confirmed: true, parameters: { plan_id: checked.id },
      });
      if (alive.current) setOperation(next);
    } catch (cause) { if (alive.current) setError((cause as Error).message + "。可点击“继续创建”查询同一提交结果。"); }
    finally { sending.current = false; if (alive.current) setBusy(false); }
  }, [cluster]);
  useEffect(() => {
    if (operation?.action === "cache.plan" && operation.state === "succeeded" && cluster && submittedPlan.current !== operation.id) {
      submittedPlan.current = operation.id; setPlan(operation); void startFromPlan(operation);
    }
  }, [operation, cluster, startFromPlan]);
  function update(next: Partial<CacheDraft>) { setDraft(current => ({ ...current, ...next })); setError(""); }
  function rowUpdate(id: string, next: Partial<CacheMachineDraft>) { setDraft(current => ({ ...current, rows: current.rows.map(row => row.machineId === id ? { ...row, ...next } : row) })); }
  async function submit(retry?: string) {
    if (!cluster || sending.current) return;
    if (!retry) {
      const problem = cacheDraftError(draft) || guidedRdmaError(draft, machines);
      if (problem) { setError(problem); return; }
      if (draft.rows.some(row => row.profileId && !profiles.some(p => p.id === row.profileId && p.revision === row.profileRevision))) { setError("缓存配置已不可用，请重新选择"); return; }
      if (draft.rows.some(row => !machines.some(machine => machine.id === row.machineId))) { setError("部署机器已不可用，请重新选择"); return; }
    }
    sending.current = true; setBusy(true); setError("");
    try {
      const parameters: Parameters = retry ? { retry_operation_id: retry } : {
        group_name: finalName, members: cacheMembers(draft),
      };
      const next = await api<Operation>("/clusters/" + encodeURIComponent(cluster.id) + "/resource-operations", "POST", {
        action: retry ? "cache.create" : "cache.plan", parameters,
        base_revision: cluster.revision, request_id: requestId(), confirmed: true,
      });
      if (alive.current) { setOperation(next); if (!retry) setPlan(next); setStep(5); }
    } catch (cause) { if (alive.current) setError((cause as Error).message); }
    finally { sending.current = false; if (alive.current) setBusy(false); }
  }
  function createAnother() {
    sessionStorage.removeItem(operationKey);
    setOperation(undefined); setPlan(undefined); setFinalName("");
    setDraft(blankCacheDraft()); setStep(1); setError(""); submittedPlan.current = "";
  }
  const backToGuide = () => onNavigate("#/start/cache");
  if (route === "#/start/cache/cluster/machine" || route === "#/start/cache/machine") return <section className="getting-started"><h1>添加机器</h1><GuidedMachineForm onDirty={onDirty} continueLabel={route.endsWith("/cluster/machine") ? "继续添加集群" : "继续创建缓存组"} onBack={() => onNavigate(route.endsWith("/cluster/machine") ? "#/start/cache/cluster" : "#/start/cache")} onCreated={id => { newMachine.current = id; onNavigate(route.endsWith("/cluster/machine") ? "#/start/cache/cluster" : "#/start/cache"); }} /></section>;
  if (route === "#/start/cache/cluster") return <section className="getting-started"><h1>添加集群</h1><DiscoverClusters guided admin={admin} userId={userId} initialMachineId={newMachine.current || undefined} onAddMachine={() => onNavigate("#/start/cache/cluster/machine")} onClose={backToGuide} onImported={ids => { update({ clusterId: ids[0], rows: [] }); setStep(1); backToGuide(); }} /></section>;
  if (route === "#/start/cache/profile") return <section className="getting-started guided-cache-flow"><h1>添加缓存组配置</h1><button onClick={backToGuide}>返回创建缓存组</button><CacheProfilesPage onDirty={onDirty} onSaved={() => { setStep(3); backToGuide(); }} /></section>;
  const resources = snapshot?.resources || [];
  const resource = resources.find(item => item.id === operation?.resource_id || item.id === plan?.resource_id);
  const members = (resource?.data.members || []) as (Parameters & { binary_info?: { path: string; version: string; sha256: string } })[];
  const detailsReady = !!draft.name.trim() && (draft.source !== "tag" || !!draft.tag && /^sha256:[0-9a-f]{64}$/.test(draft.imageDigest));
  return <section className="getting-started guided-cache-flow">
    <p className="eyebrow">GETTING STARTED / CACHE</p><h1>创建缓存组</h1>
    <section className="getting-started-card">
      <p className="muted">{step < 5 ? "步骤 " + step + " / 4" : "执行结果"}</p>
      {error && <p role="alert" className="error">{error}</p>}
      {step === 1 && <>
        <h2>选择目标集群</h2>
        <label>目标集群<select value={draft.clusterId} onChange={event => update({ clusterId: event.target.value, rows: [] })}><option value="">请选择集群</option>{clusters.map(item => <option key={item.id} value={item.id}>{item.external_name} · {item.machine_name} ({item.machine_address}) · {item.os_user}</option>)}</select></label>
        <div className="getting-started-actions"><button onClick={() => onNavigate("#/start/cache/cluster")}>先添加集群</button><button className="primary" disabled={!cluster || !snapshot?.catalog.some(item => item.action === "cache.plan")} onClick={() => setStep(2)}>下一步</button></div>
      </>}
      {step === 2 && <>
        <h2>填写缓存组信息</h2>
        <label>缓存组名称<input value={draft.name} onChange={event => update({ name: event.target.value })} placeholder="例如 test-cache" /></label>
        <label>时间后缀<select value={draft.suffix} onChange={event => update({ suffix: event.target.value as FilesystemSuffix })}><option value="none">不添加（默认）</option><option value="date">日期 YYYYMMDD</option><option value="seconds">日期时间 YYYYMMDD-HHmmss</option><option value="milliseconds">日期时间＋毫秒 YYYYMMDD-HHmmss-SSS</option></select></label>
        <label>程序来源<select value={draft.source} onChange={event => { update({ source: event.target.value as CacheDraft["source"] });  }}><option value="default">使用机器默认 dingo-cache</option><option value="tag">使用指定 TAG</option><option value="path">使用目标机器已有程序</option></select></label>
        {draft.source === "tag" && <CacheTagSelector tag={draft.tag} digest={draft.imageDigest} onChange={(tag, imageDigest) => update({ tag, imageDigest })} />}
        {draft.source === "path" && <p className="muted">下一步为每台机器分别填写已有 dingo-cache 所在目录；平台不会下载或分发。</p>}
        <div className="getting-started-actions"><button onClick={() => setStep(1)}>上一步</button><button className="primary" disabled={!detailsReady || busy} onClick={() => setStep(3)}>下一步</button></div>
      </>}
      {step === 3 && <>
        <h2>选择部署机器</h2>
        <p className="muted">新增机器会复制第一台机器当前的缓存参数，之后可独立修改；程序目录、地址和执行用户不会复制。</p>
        <div className="guided-cache-machines">{machines.map(machine => <label key={machine.id}><input type="checkbox" checked={draft.rows.some(row => row.machineId === machine.id)} onChange={event => update({ rows: event.target.checked ? [...draft.rows, draft.rows.length ? cloneCacheSettings(draft.rows[0], newCacheRow(machine), machine) : newCacheRow(machine)] : draft.rows.filter(row => row.machineId !== machine.id) })} />{machine.name} · {machine.address}</label>)}</div>
        <button onClick={() => onNavigate("#/start/cache/machine")}>先添加机器</button>
        {draft.rows.map(row => {
          const machine = machines.find(m => m.id === row.machineId);
          return machine ? <CacheMachineCard key={row.machineId} row={row} machine={machine} pathMode={draft.source === "path"}
            catalog={snapshot?.cache_parameter_catalog} profiles={snapshot?.cache_profiles || []}
            otherMachines={machines.filter(m => m.id !== row.machineId && draft.rows.some(r => r.machineId === m.id))}
            onChange={patch => rowUpdate(row.machineId, patch)}
            onSaved={saved => setSnapshot(current => current ? { ...current, cache_profiles: [...(current.cache_profiles || []).filter(p => p.id !== saved.id), saved] } : current)}
            onCopy={ids => update({ rows: draft.rows.map(target => {
              const targetMachine = machines.find(m => m.id === target.machineId);
              return ids.includes(target.machineId) && targetMachine ? cloneCacheSettings(row, target, targetMachine) : target;
            }) })} /> : <p key={row.machineId} role="alert">机器 {row.machineId} 已不可用，请返回重新选择。</p>;
        })}
        <p>{draft.rows.length} 台机器，共 {count} 个缓存节点，总配置容量 {Number((capacity / 1024).toFixed(2))} GiB。</p>
        <div className="getting-started-actions"><button onClick={() => setStep(2)}>上一步</button><button className="primary" onClick={() => { const problem = cacheDraftError(draft) || guidedRdmaError(draft, machines); if (problem) setError(problem); else { setError(""); setFinalName(formatFilesystemName(draft.name, draft.suffix, new Date())); setStep(4); } }}>下一步</button></div>
      </>}
      {step === 4 && <>
        <h2>确认并创建</h2><p>目标集群：{cluster?.external_name}</p><p>缓存组名称：{finalName}</p><p>程序：{sourceText}</p>
        <div className="guided-cache-table"><table><thead><tr><th>机器 / 用户</th><th>节点数量</th><th>缓存基础目录</th><th>每节点容量</th><th>一致性哈希权重</th><th>程序目录</th></tr></thead><tbody>{draft.rows.map(row => <tr key={row.machineId}><td>{machines.find(item => item.id === row.machineId)?.name} / {row.user}</td><td>{row.count}</td><td>{row.directory}</td><td>{row.capacity / capacityFactors[row.capacityUnit || "MiB"]} {row.capacityUnit || "MiB"}</td><td>{row.weight ?? Number(row.options?.group_weight ?? 100)}</td><td>{draft.source === "path" ? row.binaryDirectory : sourceText}</td></tr>)}</tbody></table></div>
        {draft.rows.map(row => <details key={row.machineId}><summary>{machines.find(m => m.id === row.machineId)?.name} · 最终参数</summary><pre>{JSON.stringify(machineCacheOptions(row), null, 2)}</pre></details>)}
        <p>全部 {count} 个节点加入同一缓存组。先准备并分发程序，检查所有机器的程序、目录和端口，通过后自动创建。</p>
        <div className="getting-started-actions"><button disabled={busy} onClick={() => setStep(3)}>返回修改</button><button className="primary" disabled={busy} onClick={() => void submit()}>{busy ? "提交中…" : "检查并创建缓存组"}</button></div>
      </>}
      {step === 5 && operation && <>
        <h2>{operation.action === "cache.plan" ? "准备与分发程序并检查部署环境" : operation.state === "succeeded" ? "缓存组创建完成" : "缓存组创建进度"}</h2>
        <ResourceOperationView operation={operation} label={operation.action === "cache.plan" ? "程序和端口检查" : "创建缓存组"} canManage onChange={setOperation} />
        {!!members.length && <div className="guided-cache-table"><table><thead><tr><th>机器 / 节点</th><th>状态</th><th>监听地址</th><th>程序版本 / 路径</th></tr></thead><tbody>{members.map(member => <tr key={String(member.member_id)}><td>{machines.find(item => item.id === member.machine_id)?.name || String(member.machine_id)}<br />{String(member.member_id)}</td><td>{member.process_state === "running" ? "成功" : member.process_state === "unknown" ? "失败或结果待核实" : "待启动"}</td><td>{String(member.listen_ip)}:{String(member.listen_port)}</td><td>{member.binary_info?.version}<br />{member.binary_info?.path || "等待程序检查"}</td></tr>)}</tbody></table></div>}
        <div className="getting-started-actions">
          {operation.action === "cache.plan" && operation.state === "succeeded" && error && <button disabled={busy} onClick={() => void startFromPlan(operation)}>继续创建</button>}
          {operation.action === "cache.plan" && !active && operation.state !== "succeeded" && <button onClick={() => { setOperation(undefined); sessionStorage.removeItem(operationKey); setStep(3); }}>返回修改并重新检查</button>}
          {operation.action === "cache.create" && ["failed", "interrupted", "cancelled", "unknown"].includes(operation.state) && <button disabled={busy} onClick={() => void submit(operation.id)}>重试失败及未完成节点</button>}
          <button onClick={() => onNavigate("#/clusters/" + draft.clusterId + "/resources")}>查看缓存组</button>
          {operation.action === "cache.create" && operation.state === "succeeded" && <><button onClick={() => onNavigate("#/clusters/" + draft.clusterId + "/resources")}>继续挂载文件系统</button><button onClick={createAnother}>再创建一个缓存组</button></>}
        </div>
      </>}
    </section>
  </section>;
}
