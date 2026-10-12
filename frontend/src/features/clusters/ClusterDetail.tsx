import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { copyText } from "../../clipboard";
import { ClusterControl } from "./ClusterControl";
import { ClusterTopology } from "./ClusterTopology";
import { OperationAuthDialog } from "./OperationAuthDialog";
import { logAccessReason, type RemoteTargets } from "../remote/types";
import {
  type ClusterDetailData,
  type Operation,
  dateText,
  statusNames,
} from "./types";
export function ClusterDetail({
  id,
  admin,
  userId,
  onBack,
  onDirty,
  onDiscover,
}: {
  id: string;
  admin: boolean;
  userId?: string;
  onBack: () => void;
  onDirty: (v: boolean) => void;
  onDiscover: () => void;
}) {
  const [data, setData] = useState<ClusterDetailData>(),
    [op, setOp] = useState<Operation>(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [role, setRole] = useState(""),
    [host, setHost] = useState(""),
    [state, setState] = useState(""),
    [editing, setEditing] = useState(false),
    [name, setName] = useState(""),
    [copied, setCopied] = useState<{
      key?: string;
      message: string;
      failed: boolean;
    }>();
  const copySequence = useRef(0);
  const [remoteTargets, setRemoteTargets] = useState<RemoteTargets>();
  const [terminalMachine, setTerminalMachine] = useState("");
  useEffect(() => {
    let active = true;
    api<RemoteTargets>(`/clusters/${encodeURIComponent(id)}/remote-targets`)
      .then((targets) => {
        if (active) setRemoteTargets(targets);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [id, data?.revision, data?.status_success_at]);
  const live = useRef(true);
  const completed = useRef("");
  const load = useCallback(async () => {
    const row = await api<ClusterDetailData>("/clusters/" + id);
    if (live.current) {
      setData(row);
    }
    return row;
  }, [id]);
  const refresh = useCallback(
    async (row: ClusterDetailData) => {
      setBusy(true);
      setError("");
      try {
        const o = await api<Operation>(
          `/clusters/${id}/refresh-status`,
          "POST",
          { base_revision: row.revision },
        );
        if (live.current) setOp(o);
      } catch (e) {
        if (live.current) setError((e as Error).message);
      } finally {
        if (live.current) setBusy(false);
      }
    },
    [id],
  );
  useEffect(() => {
    live.current = true;
    let active = true;
    load()
      .then((row) => {
        if (
          active &&
          (admin || (!!userId && row.creator_id === userId)) &&
          !row.archived &&
          row.binding_state === "verified"
        )
          refresh(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
      live.current = false;
    };
  }, [load, refresh, admin, userId]);
  useEffect(() => {
    if (
      op &&
      ["succeeded", "failed", "cancelled", "interrupted"].includes(op.state) &&
      completed.current !== op.id + op.state
    ) {
      completed.current = op.id + op.state;
      load().catch((e) => setError(e.message));
    }
  }, [op, load]);
  const controlCompleted = useCallback(() => {
    load()
      .then((row) => refresh(row))
      .catch((e) => {
        if (live.current) setError(e.message);
      });
  }, [load, refresh]);
  async function edit(e: React.FormEvent) {
    e.preventDefault();
    if (!data) return;
    setBusy(true);
    try {
      const row = await api<ClusterDetailData>("/clusters/" + id, "PATCH", {
        base_revision: data.revision,
        name,
      });
      if (live.current) {
        setData(row);
        setEditing(false);
        onDirty(false);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function archive() {
    if (
      !data ||
      !confirm(
        data.archived
          ? "恢复该集群登记？"
          : "归档该集群登记？不会操作远端集群。",
      )
    )
      return;
    setBusy(true);
    try {
      const row = await api<ClusterDetailData>("/clusters/" + id, "PATCH", {
        base_revision: data.revision,
        archived: !data.archived,
      });
      if (live.current) setData(row);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function copy(value: string, key?: string) {
    const sequence = ++copySequence.current;
    setCopied(undefined);
    try {
      await copyText(value);
      if (sequence === copySequence.current)
        setCopied({ key, message: "已复制", failed: false });
    } catch {
      if (sequence === copySequence.current)
        setCopied({
          key,
          message: "复制失败，请选中文本后手动复制。",
          failed: true,
        });
    }
  }
  if (!data)
    return (
      <section className="panel">
        <button onClick={onBack}>返回集群概览</button>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : (
          <p>正在读取集群详情…</p>
        )}
      </section>
    );
  const canEdit = admin || (!!userId && data.creator_id === userId);
  const snapshot = data.status_snapshot;
  const firstMdsAddress = snapshot?.mds_addresses?.[0]?.trim();
  const dashboardUrl = firstMdsAddress
    ? /^https?:\/\//i.test(firstMdsAddress)
      ? firstMdsAddress
      : `http://${firstMdsAddress}`
    : undefined;
  const services = snapshot?.services || [];
  const filtered = services
    .filter(
      (s) =>
        (!role || s.role === role) &&
        s.host.toLowerCase().includes(host.toLowerCase()) &&
        (!state || s.state === state),
    )
    .sort(
      (a, b) => Number(a.state === "running") - Number(b.state === "running"),
    );
  const raw = data.status_output;
  const terminalTargets = remoteTargets?.items || [];
  const selectedTerminal = terminalTargets.some(
    (t) => t.machine_id === terminalMachine,
  )
    ? terminalMachine
    : terminalTargets[0]?.machine_id;
  const active = busy || (!!op && ["pending", "running"].includes(op.state));
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / CLUSTER</p>
          <h1>
            {dashboardUrl ? (
              <a
                href={dashboardUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="打开 DingoFS 看板"
              >
                {data.external_name}
              </a>
            ) : (
              data.external_name
            )}
          </h1>
          <p>别名：{data.name}</p>
          <p>
            {data.machine_name} · {data.machine_address} · 执行用户{" "}
            {data.os_user}
          </p>
          <small>
            最近成功采集：{dateText(data.status_success_at) || "尚未采集"}
          </small>
        </div>
        <div className="actions">
          <button onClick={onBack}>返回集群概览</button>

          <button
            className="primary"
            disabled={
              !canEdit ||
              active ||
              data.archived ||
              data.binding_state !== "verified"
            }
            onClick={() => refresh(data)}
          >
            刷新状态
          </button>
          {canEdit && (
            <button
              disabled={busy}
              onClick={() => {
                setName(data.name);
                setEditing(true);
                onDirty(true);
              }}
            >
              编辑登记信息
            </button>
          )}
        </div>
      </header>
      <div className="cluster-resource-entry">
        <a
          className="cluster-resource-card"
          href={`#/clusters/${encodeURIComponent(id)}/resources`}
          aria-label="资源管理"
          aria-describedby="cluster-resource-summary"
        >
          <span className="cluster-resource-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="2" />
              <rect x="14" y="3" width="7" height="7" rx="2" />
              <rect x="3" y="14" width="7" height="7" rx="2" />
              <path d="M14 17.5h7M17.5 14v7" />
            </svg>
          </span>
          <span className="cluster-resource-copy">
            <strong>资源管理</strong>
            <span id="cluster-resource-summary">文件系统 · 缓存组 · 挂载管理</span>
          </span>
          <span className="cluster-resource-go" aria-hidden="true">进入管理 <span>→</span></span>
        </a>
        <div className="cluster-resource-tooltip" role="tooltip">
          <strong>集群日常操作入口</strong>
          <span>文件系统：创建、查询、删除、配额、回收站和目录统计</span>
          <span>缓存组：创建与添加成员、停止、删除和成员管理</span>
          <span>挂载管理：挂载文件系统、卸载和查看客户端日志</span>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data.binding_state !== "verified" && (
        <section className="panel">
          <h2>需要确认管理入口</h2>
          <p>已有登记保留，重新发现集群后确认入口，再读取状态。</p>
          {canEdit && <button onClick={onDiscover}>发现集群</button>}
        </section>
      )}
      {editing && (
        <form className="panel" onSubmit={edit}>
          <h2>编辑登记信息</h2>
          <label>
            别名
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <p>更换机器、执行用户或目标集群，需要重新发现并确认绑定。</p>
          <div className="actions">
            <button disabled={busy}>保存</button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                onDirty(false);
              }}
            >
              取消
            </button>
            <button type="button" disabled={busy} onClick={archive}>
              {data.archived ? "恢复登记" : "归档登记"}
            </button>
          </div>
        </form>
      )}
      {op && <OperationAuthDialog operation={op} onChange={setOp} />}
      <section className="panel">
        <div className="cluster-summary">
          <div>
            <small>集群类型</small>
            <strong>{snapshot?.cluster_kind || "—"}</strong>
          </div>
          <div>
            <small>运行状态</small>
            <strong>{statusNames[snapshot?.state || "unknown"]}</strong>
          </div>
          <div>
            <small>节点数 / 服务数</small>
            <strong>
              {snapshot
                ? `${snapshot.node_count} / ${snapshot.service_count}`
                : "—"}
            </strong>
          </div>
          <div>
            <small>运行 / 预期实例</small>
            <strong>
              {snapshot
                ? `${snapshot.running_instances} / ${snapshot.expected_instances}`
                : "—"}
            </strong>
          </div>
        </div>
        <p className="muted">
          运行状态仅反映服务进程，不代表业务健康。最近采集：
          {statusNames[data.status_attempt_state] ||
            data.status_attempt_state}{" "}
          {dateText(data.status_attempt_at)}
        </p>
        {data.status_error_code && (
          <p className="error">
            采集未成功（{data.status_error_code}），以上保留最近成功数据。
          </p>
        )}
        <dl>
          {[
            ["MDS 地址", snapshot?.mds_addresses],
            ["TiKV 地址", snapshot?.tikv_addresses],
          ].map(([label, addresses]) => (
            <div key={label as string}>
              <dt>{label}</dt>
              <dd>
                {(addresses as string[] | undefined)?.join(", ") || "—"}{" "}
                {!!addresses?.length && (
                  <button
                    onClick={() => copy((addresses as string[]).join(","))}
                  >
                    复制
                  </button>
                )}
              </dd>
            </div>
          ))}
        </dl>
        <div className="actions">
          {Object.entries(snapshot?.role_counts || {}).map(([key, count]) => (
            <span className="badge" key={key}>
              {key} · {count}
            </span>
          ))}
        </div>
      </section>
      {admin && !data.archived && terminalTargets.length > 0 && (
        <section className="panel">
          <div className="remote-terminal-launch">
            <label>
              终端目标
              <select
                aria-label="终端目标"
                value={selectedTerminal}
                onChange={(e) => setTerminalMachine(e.target.value)}
              >
                {terminalTargets.map((target) => (
                  <option key={target.machine_id} value={target.machine_id}>
                    {target.name} · {target.address} · {target.ssh_user}
                  </option>
                ))}
              </select>
            </label>
            <a
              className="button"
              target="_blank"
              rel="noopener noreferrer"
              href={`#/clusters/${encodeURIComponent(id)}/terminal/${encodeURIComponent(selectedTerminal || "")}`}
            >
              打开终端 ↗
            </a>
          </div>
          <small className="muted">在新标签页确认机器和 SSH 用户后连接。</small>
        </section>
      )}
      <section className="panel">
        <h2>服务实例</h2>
        <div className="cluster-filters">
          <label>
            角色
            <select
              aria-label="角色"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              <option value="">全部角色</option>
              {Object.keys(snapshot?.role_counts || {}).map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <label>
            主机
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="搜索主机"
            />
          </label>
          <label>
            状态
            <select
              aria-label="状态"
              value={state}
              onChange={(e) => setState(e.target.value)}
            >
              <option value="">全部状态</option>
              {["running", "degraded", "stopped", "unknown"].map((s) => (
                <option key={s} value={s}>
                  {statusNames[s]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="cluster-services-scroll">
          <table className="cluster-services">
            <thead>
              <tr>
                {[
                  "服务 ID",
                  "角色",
                  "主机",
                  "实例",
                  "容器 ID",
                  "运行状态",
                  "端口",
                  "目录",
                  "日志",
                ].map((n) => (
                  <th key={n}>{n}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr
                  key={s.id}
                  className={
                    s.state === "degraded" ? "cluster-service-error" : ""
                  }
                >
                  <td>{s.id}</td>
                  <td>{s.role}</td>
                  <td>
                    {data.node_links?.[s.host] ? (
                      <a
                        href={`#/machines/${data.node_links?.[s.host]}`}
                        onClick={(e) => {
                          e.preventDefault();
                          window.dispatchEvent(
                            new CustomEvent("platform-navigate", {
                              detail: {
                                kind: "machines",
                                id: data.node_links?.[s.host],
                              },
                            }),
                          );
                        }}
                      >
                        {s.host}
                      </a>
                    ) : (
                      <>
                        {s.host}
                        <small className="muted">
                          {" "}
                          ·{" "}
                          {remoteTargets?.services?.find(
                            (row) => row.id === s.id,
                          )?.match_state === "ambiguous"
                            ? "匹配冲突"
                            : "未匹配机器资源"}
                        </small>
                      </>
                    )}
                  </td>
                  <td>
                    {s.running_instances}/{s.expected_instances}
                  </td>
                  <td>{s.container_id || "—"}</td>
                  <td>{s.status_text}</td>
                  <td>{s.ports.join(", ") || "—"}</td>
                  <td>
                    <details>
                      <summary>查看目录</summary>
                      {[
                        ["日志目录", s.log_dir],
                        ["数据目录", s.data_dir],
                        ["Raft 目录", s.raft_dir],
                      ].map(([label, value]) => (
                        <div className="cluster-directory" key={label}>
                          <strong>{label}</strong>
                          <code>{value || "未提供"}</code>
                          {value && (
                            <button
                              type="button"
                              onClick={() => copy(value, `${s.id}:${label}`)}
                            >
                              复制路径
                            </button>
                          )}
                          {copied?.key === `${s.id}:${label}` && (
                            <span
                              role="status"
                              className={copied.failed ? "error" : "muted"}
                            >
                              {copied.message}
                            </span>
                          )}
                        </div>
                      ))}
                    </details>
                  </td>
                  <td>
                    <a
                      href={`#/clusters/${encodeURIComponent(id)}/logs/${encodeURIComponent(s.id)}`}
                    >
                      查看日志
                    </a>
                    {remoteTargets?.services &&
                      logAccessReason(
                        remoteTargets.services.find((row) => row.id === s.id),
                      ) && (
                        <small className="remote-access-hint">
                          {logAccessReason(
                            remoteTargets.services.find(
                              (row) => row.id === s.id,
                            ),
                          )}
                        </small>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!filtered.length && <p className="empty">没有可展示的服务实例</p>}
        {copied && !copied.key && <p role="status">{copied.message}</p>}
      </section>
      <ClusterControl
        id={id}
        name={data.external_name}
        revision={data.revision}
        services={services}
        canOperate={
          canEdit &&
          !data.archived &&
          data.binding_state === "verified" &&
          !active
        }
        onComplete={controlCompleted}
      />
      <section className="panel">
        <details>
          <summary>原始输出与查询信息</summary>
          <p>
            目标：{data.external_name} · 退出码：
            {raw?.returncode == null ? "—" : String(raw.returncode)}
          </p>
          <pre className="cluster-raw">
            {String(raw?.stdout || "暂无输出")}
            {raw?.stderr ? "\n" + String(raw.stderr) : ""}
          </pre>
        </details>
      </section>
      {!data.archived && data.binding_state === "verified" && (
        <ClusterTopology
          canOperate={canEdit}
          key={`topology-${id}`}
          id={id}
          revision={data.revision}
        />
      )}
    </>
  );
}
