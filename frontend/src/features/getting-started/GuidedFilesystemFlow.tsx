import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ClusterRow } from "../clusters/types";
import type { StorageProfile } from "../storage/types";
import { ResourceOperationView } from "../resources/ResourceOperationView";
import { requestId } from "../resources/requestId";
import type { ResourceOperation, ResourceSnapshot } from "../resources/types";

type Step = "cluster" | "details" | "confirm" | "result";
const draftKey = "guided-filesystem-draft";
type Draft = { clusterId: string; fsName: string; storageId: string; partition: "hash" | "monolithic" };
function readDraft(): Draft {
  try {
    const saved = JSON.parse(sessionStorage.getItem(draftKey) || "null") as Partial<Draft> | null;
    if (saved && typeof saved.clusterId === "string" && typeof saved.fsName === "string" && typeof saved.storageId === "string")
      return { clusterId: saved.clusterId, fsName: saved.fsName, storageId: saved.storageId, partition: saved.partition === "monolithic" ? "monolithic" : "hash" };
  } catch { /* Ignore an invalid previous draft. */ }
  return { clusterId: "", fsName: "", storageId: "", partition: "hash" };
}
export function GuidedFilesystemFlow({ admin, userId, onNavigate, onDirty }: {
  admin: boolean;
  userId?: string;
  onNavigate: (hash: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft>(readDraft);
  const [step, setStep] = useState<Step>("cluster");
  const [clusters, setClusters] = useState<ClusterRow[]>([]);
  const [profiles, setProfiles] = useState<StorageProfile[]>([]);
  const [snapshot, setSnapshot] = useState<ResourceSnapshot>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [operation, setOperation] = useState<ResourceOperation>();
  const [uncertain, setUncertain] = useState(false);
  const live = useRef(true);
  const submitting = useRef(false);
  const cluster = clusters.find((item) => item.id === draft.clusterId);
  const availableClusters = clusters.filter((item) => !item.archived && item.binding_state === "verified" && (admin || (!!userId && item.creator_id === userId)));
  const availableProfiles = profiles.filter((item) => item.enabled && item.has_secrets);
  const profile = availableProfiles.find((item) => item.id === draft.storageId);
  const ready = !!cluster && !!profile && !!draft.fsName.trim() && profile.revision > 0;
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const all: ClusterRow[] = [];
      let offset = 0;
      while (true) {
        const page = await api<{ items: ClusterRow[]; total: number }>(`/clusters/overview?limit=200&offset=${offset}`);
        all.push(...page.items);
        offset += page.items.length;
        if (!page.items.length || offset >= page.total) break;
      }
      const storage = await api<StorageProfile[]>("/storage-profiles");
      if (live.current) { setClusters(all); setProfiles(storage); }
    } catch (cause) {
      if (live.current) setError((cause as Error).message);
    } finally {
      if (live.current) setLoading(false);
    }
  }, []);
  useEffect(() => { live.current = true; void load(); return () => { live.current = false; onDirty(false); }; }, [load, onDirty]);
  useEffect(() => {
    if (step !== "result") sessionStorage.setItem(draftKey, JSON.stringify(draft));
    onDirty(step !== "result" && (!!draft.clusterId || !!draft.fsName || !!draft.storageId));
  }, [draft, step, onDirty]);
  useEffect(() => {
    if (!draft.clusterId) { setSnapshot(undefined); return; }
    let active = true;
    setSnapshot(undefined);
    api<ResourceSnapshot>(`/clusters/${encodeURIComponent(draft.clusterId)}/resources`)
      .then((value) => { if (active) setSnapshot(value); })
      .catch((cause) => { if (active) setError((cause as Error).message); });
    return () => { active = false; };
  }, [draft.clusterId]);
  function update(next: Partial<Draft>) { setDraft((current) => ({ ...current, ...next })); setError(""); }
  async function create() {
    if (!ready || !snapshot?.catalog.some((item) => item.action === "fs.create") || busy || submitting.current || uncertain) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await api<ResourceOperation>(`/clusters/${encodeURIComponent(cluster.id)}/resource-operations`, "POST", {
        base_revision: cluster.revision,
        request_id: requestId(),
        action: "fs.create",
        parameters: { fs_name: draft.fsName.trim(), partition_type: draft.partition, storage_profile_id: profile.id, storage_profile_revision: profile.revision },
        confirmed: true,
      });
      if (!live.current) return;
      sessionStorage.removeItem(draftKey);
      onDirty(false);
      setOperation(next);
      setStep("result");
    } catch (cause) {
      if (!live.current) return;
      if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422, 429].includes(cause.status))
        setError(`${cause.message}。本次请求未创建新任务。`);
      else { setUncertain(true); setError(`${(cause as Error).message}。请求可能已发出，请先到资源管理核实，避免重复创建。`); }
    } finally { submitting.current = false; if (live.current) setBusy(false); }
  }
  return <section className="getting-started-card guided-filesystem-flow" aria-label="创建文件系统引导">
    <p className="muted">步骤 {step === "cluster" ? 1 : step === "details" ? 2 : step === "confirm" ? 3 : 3} / 3</p>
    {loading && <p role="status">正在读取集群与存储配置…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {step === "cluster" && <>
      <h2>选择目标集群</h2>
      <label>目标集群<select value={draft.clusterId} onChange={(event) => update({ clusterId: event.target.value, storageId: "" })} disabled={loading}>
        <option value="">请选择集群</option>
        {availableClusters.map((item) => <option key={item.id} value={item.id}>{item.external_name} · {item.machine_name} ({item.machine_address}) · {item.os_user}</option>)}
      </select></label>
      {!loading && !availableClusters.length && <p>还没有可用集群。请先添加集群，并确保集群状态已成功采集。</p>}
      <div className="getting-started-actions"><button type="button" onClick={() => onNavigate("#/start")}>返回开始页</button>
        {!availableClusters.length && <button type="button" onClick={() => { sessionStorage.setItem("guided-filesystem-return", "1"); onNavigate("#/start/cluster"); }}>先添加集群</button>}
        <button className="primary" type="button" disabled={!availableClusters.some((item) => item.id === draft.clusterId) || !snapshot} onClick={() => setStep("details")}>下一步</button></div>
    </>}
    {step === "details" && <>
      <h2>填写文件系统信息</h2>
      <label>文件系统名称<input required value={draft.fsName} onChange={(event) => update({ fsName: event.target.value })} /></label>
      <label>存储配置<select value={draft.storageId} onChange={(event) => update({ storageId: event.target.value })}>
        <option value="">请选择存储配置</option>
        {availableProfiles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.storage_type.toUpperCase()}</option>)}
      </select></label>
      {profile && <p className="muted">{profile.storage_type.toUpperCase()} · {profile.storage_type === "s3" ? `${profile.parameters.s3_endpoint || "—"} / ${profile.parameters.s3_bucketname || "—"}` : `${profile.parameters.rados_mon || "—"} / ${profile.parameters.rados_poolname || "—"}`} · 访问凭据已配置</p>}
      {!availableProfiles.length && <p>没有已启用且凭据齐全的存储配置。</p>}
      <details><summary>高级选项</summary><label>分区类型<select value={draft.partition} onChange={(event) => update({ partition: event.target.value as Draft["partition"] })}><option value="hash">hash（默认）</option><option value="monolithic">monolithic</option></select></label></details>
      <div className="getting-started-actions"><button type="button" onClick={() => setStep("cluster")}>上一步</button>
        <button type="button" onClick={() => onNavigate("#/storage")}>前往添加存储配置</button>
        <button className="primary" type="button" disabled={!ready} onClick={() => setStep("confirm")}>下一步</button></div>
    </>}
    {step === "confirm" && <>
      <h2>确认创建信息</h2>
      <dl className="getting-started-summary"><div><dt>目标集群</dt><dd>{cluster?.external_name}</dd></div><div><dt>文件系统名称</dt><dd>{draft.fsName.trim()}</dd></div><div><dt>存储配置</dt><dd>{profile?.name}</dd></div><div><dt>分区类型</dt><dd>{draft.partition}</dd></div></dl>
      <div className="getting-started-actions"><button type="button" disabled={busy} onClick={() => setStep("details")}>返回修改</button><button className="primary" type="button" disabled={!ready || !snapshot?.catalog.some((item) => item.action === "fs.create") || busy || uncertain} onClick={() => void create()}>{busy ? "提交中…" : "确认创建"}</button></div>
      {uncertain && <button type="button" onClick={() => onNavigate(`#/clusters/${encodeURIComponent(draft.clusterId)}/resources`)}>前往资源管理核实</button>}
    </>}
    {step === "result" && operation && <>
      <h2>{operation.state === "succeeded" ? "文件系统创建成功" : "文件系统创建进度"}</h2>
      <ResourceOperationView operation={operation} label="创建文件系统" canManage onChange={setOperation} />
      {operation.state === "succeeded" && <div className="getting-started-actions"><button className="primary" type="button" onClick={() => onNavigate(`#/clusters/${encodeURIComponent(draft.clusterId)}/resources`)}>查看文件系统</button><button type="button" onClick={() => onNavigate(`#/clusters/${encodeURIComponent(draft.clusterId)}/resources`)}>前往资源管理并挂载</button></div>}
      {["failed", "cancelled", "interrupted", "unknown"].includes(operation.state) && <div className="getting-started-actions"><button type="button" onClick={() => onNavigate(`#/clusters/${encodeURIComponent(draft.clusterId)}/resources`)}>查看资源操作</button><button type="button" onClick={() => setStep("details")}>返回修改</button></div>}
    </>}
  </section>;
}
