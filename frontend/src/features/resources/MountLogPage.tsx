import { requestId } from "./requestId";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { LogFileTable } from "../remote/LogFileTable";
import { LogDirectorySearch } from "../remote/LogDirectorySearch";
import { LogLoading } from "../remote/LogLoading";
import { filterLog, appendLog } from "../remote/logBuffer";
import type { RemoteFile } from "../remote/types";
import type { ResourceOperation, ResourceSnapshot, SavedResource } from "./types";

const finished = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
export function mountLogUrl(clusterId: string, resourceId: string, fileName?: string) {
  const path = `#/clusters/${encodeURIComponent(clusterId)}/resources/mounts/${encodeURIComponent(resourceId)}/logs`;
  return fileName === undefined ? path : `${path}?file=${encodeURIComponent(fileName)}`;
}
export function mountLogRoute(hash: string) {
  const [path, query = ""] = hash.split("?", 2);
  const match = path.match(/^#\/clusters\/([^/]+)\/resources\/mounts\/([^/]+)\/logs$/);
  if (!match) return undefined;
  try {
    const fileName = new URLSearchParams(query).get("file");
    const params = new URLSearchParams(query);
    return { clusterId: decodeURIComponent(match[1]), resourceId: decodeURIComponent(match[2]), ...(fileName === null ? {} : { fileName }), ...(params.has("search") && params.has("match") ? { searchKeyword: params.get("search")!, searchFile: params.get("match")!, searchCaseSensitive: params.get("case") === "1" } : {}) };
  } catch { return undefined; }
}

function rows(value: unknown): RemoteFile[] {
  if (!Array.isArray(value)) return [];
  return value.filter(row => row && typeof row === "object" && typeof row.name === "string")
    .map(row => ({ file_id: row.name, name: row.name, size: Number(row.size) || 0, mtime: Number(row.mtime) || 0 }));
}
function resultData(operation: ResourceOperation): Record<string, unknown> {
  if (operation.state !== "succeeded") throw new Error(operation.message || operation.error_code || "日志查询失败");
  const step = operation.result?.steps?.[0];
  if (!step || step.returncode !== 0 || !step.data || typeof step.data !== "object" || Array.isArray(step.data))
    throw new Error(step?.message || step?.stderr || "日志查询没有返回有效结果");
  return step.data as Record<string, unknown>;
}
export function MountLogPage({ clusterId, resourceId, fileName }: { clusterId: string; resourceId: string; fileName?: string }) {
  const [resource, setResource] = useState<SavedResource>();
  const [clusterName, setClusterName] = useState("");
  const [machineName, setMachineName] = useState("");
  const [files, setFiles] = useState<RemoteFile[]>([]);
  const [text, setText] = useState("");
  const [truncated, setTruncated] = useState(false);
  const [lines, setLines] = useState<100 | 500 | 1000>(500);
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    setBusy(true); setError(""); setFiles([]); setText("");
    async function run() {
      try {
        const [cluster, inventory] = await Promise.all([
          api<{ external_name: string; revision: number }>(`/clusters/${encodeURIComponent(clusterId)}`),
          api<ResourceSnapshot>(`/clusters/${encodeURIComponent(clusterId)}/resources`),
        ]);
        if (!live) return;
        const mount = inventory.resources.find(row => row.id === resourceId && row.kind === "mount");
        if (!mount) throw new Error("未找到此集群的挂载记录");
        setResource(mount); setClusterName(cluster.external_name);
        setMachineName(inventory.machines.find(row => row.id === mount.data.machine_id)?.name || String(mount.data.machine_id || "—"));
        // A URL filename is never sent to the reader until a fresh listing has confirmed it.
        const list = await query(cluster.revision, "");
        if (!live) return;
        const entries = rows(list.files);
        setFiles(entries);
        setTruncated(Boolean(list.truncated));
        if (fileName !== undefined) {
          if (entries.filter(entry => entry.name === fileName).length !== 1) throw new Error(`未找到日志文件：${fileName}`);
          const content = await query(cluster.revision, fileName);
          if (live) { setText(appendLog({ text: "", truncated: false }, String(content.text || "")).text); setTruncated(Boolean(content.truncated)); }
        }
      } catch (cause) { if (live) setError((cause as Error).message); }
      finally { if (live) setBusy(false); }
    }
    async function query(baseRevision: number, filename: string): Promise<Record<string, unknown>> {
      const operation = await api<ResourceOperation>(`/clusters/${encodeURIComponent(clusterId)}/resource-operations`, "POST", {
        action: "mount.logs", parameters: { resource_id: resourceId, ...(filename ? { filename, lines } : {}) },
        base_revision: baseRevision, request_id: requestId(), confirmed: false,
      });
      let current = operation;
      while (live && !finished.has(current.state)) {
        await new Promise(resolve => setTimeout(resolve, 500));
        if (!live) break;
        current = await api<ResourceOperation>(`/resource-operations/${encodeURIComponent(operation.id)}`);
      }
      if (!live) return {};
      return resultData(current);
    }
    void run();
    return () => { live = false; };
  }, [clusterId, resourceId, fileName, lines, refresh]);
  useEffect(() => {
    const previous = document.title;
    document.title = `${fileName ? fileName + " · " : ""}${clusterName || "集群"} · 客户端日志`;
    return () => { document.title = previous; };
  }, [clusterName, fileName]);
  return <>
    <header className="page-header remote-header">
      <div><p className="eyebrow">PLATFORM / CLIENT LOGS</p><h1>{clusterName || "集群"} · 客户端日志</h1><p>{resource?.name || resourceId}</p></div>
      <div className="actions">
        {fileName !== undefined && <a className="button" href={mountLogUrl(clusterId, resourceId)}>返回日志列表</a>}
        <a className="button" href={`#/clusters/${encodeURIComponent(clusterId)}/resources`}>返回资源管理</a>
      </div>
    </header>
    <section className="panel remote-context"><dl>
      <div><dt>目标机器</dt><dd>{machineName || "—"}</dd></div>
      <div><dt>读取用户</dt><dd>{String(resource?.data.target_user || "—")}</dd></div>
      <div><dt>挂载路径</dt><dd><code>{String(resource?.data.mount_path || "—")}</code></dd></div>
      <div><dt>日志目录</dt><dd><code>{String(resource?.data.log_dir || "—")}</code></dd></div>
    </dl></section>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="remote-log-layout remote-log-directory"><section className="panel remote-files">
      <div className="section-title"><h2>{fileName === undefined ? "日志文件" : "文件访问"}</h2><button disabled={busy} onClick={() => setRefresh(value => value + 1)}>{fileName === undefined ? "刷新列表" : "重新读取"}</button></div>
      <p className="muted">{fileName === undefined ? "单击选中，双击或按 Enter 在新标签页查看。点击列名切换排序。" : `文件名：${fileName}`}</p>
      {busy && <LogLoading label="正在读取客户端日志…" popup />}
      {fileName === undefined && <LogFileTable files={files} disabled={busy} onOpen={row => window.open(mountLogUrl(clusterId, resourceId, row.name), "_blank", "noopener,noreferrer")} />}
      {fileName === undefined && !busy && !error && files.length === 0 && <p className="empty">目录中没有可读取的普通日志文件</p>}
      {truncated && fileName === undefined && <p role="status">文件列表已截断。</p>}
    </section></div>
    {fileName === undefined && resource && <LogDirectorySearch clusterId={clusterId} serviceId={`mount:${resourceId}`} fileUrl={name => mountLogUrl(clusterId, resourceId, name)} />}
    {fileName !== undefined && <section className="panel remote-log-main">
      <div className="section-title"><h2>{fileName}</h2></div>
      <div className="remote-log-toolbar"><label>末尾行数<select aria-label="末尾行数" value={lines} disabled={busy} onChange={event => setLines(Number(event.target.value) as 100 | 500 | 1000)}><option value={100}>100 行</option><option value={500}>500 行</option><option value={1000}>1000 行</option></select></label><label>过滤当前内容<input aria-label="过滤当前内容" placeholder="字面量关键词" value={keyword} onChange={event => setKeyword(event.target.value)} /></label></div>
      {truncated && <p className="remote-notice" role="status">仅展示本次末尾读取范围内的内容，较早内容已截断。</p>}
      <pre className="remote-log-output" aria-label="日志内容" tabIndex={0}>{filterLog(text, keyword)}</pre>
    </section>}
  </>;
}
