import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { bytes } from "../inventory/MachineHardware";
import {
  clusterHealth, currentUsage, fullDisks, label, machineHealth, priority, reason,
  type Cluster, type Dashboard, type Health, type Machine,
} from "./health";

function age(value: string | null | undefined, now: number) {
  if (!value) return "尚未检查";
  const elapsed = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  if (!Number.isFinite(elapsed)) return "检查时间未知";
  if (elapsed < 60) return "刚刚";
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)} 分钟前`;
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)} 小时前`;
  return `${Math.floor(elapsed / 86400)} 天前`;
}
function HealthBadge({ state }: { state: Health }) {
  return <span className={`dashboard-health dashboard-health-${state}`}>{label[state]}</span>;
}
function PercentBar({ value, alert = false }: { value: number | null; alert?: boolean }) {
  if (value == null || !Number.isFinite(value)) return <span className="muted">—</span>;
  return <span className="dashboard-meter"><strong>{Number(value.toFixed(2))}%</strong>
    <span className="dashboard-meter-track" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <span className={alert ? "dashboard-meter-fill dashboard-meter-alert" : "dashboard-meter-fill"} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </span></span>;
}
function Stat({ label: title, value, detail }: { label: string; value: number; detail: string }) {
  return <div className="dashboard-stat"><span>{title}</span><strong>{value}</strong><small>{detail}</small></div>;
}
export function DashboardPage({ userId }: { userId: string }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState(false);
  const [issuesOnly, setIssuesOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ field: "cpu" | "memory" | "disk"; descending: boolean } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await api<Dashboard>("/dashboard");
        if (active) { setData(result); setError(""); setNow(Date.now()); }
      } catch (e) { if (active) setError((e as Error).message); }
      finally { if (active) setLoading(false); }
    };
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, 15_000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  async function refresh() {
    setRefreshing(true);
    try {
      const result = await api<{ started: boolean }>("/dashboard/refresh", "POST");
      if (!result.started) setError("检查正在进行，或刚刚完成；页面会自动更新结果。");
      else setError("");
      setData(await api<Dashboard>("/dashboard"));
      setNow(Date.now());
    } catch (e) { setError((e as Error).message); }
    finally { setRefreshing(false); }
  }
  const machines = useMemo(() => (data?.machines || [])
    .filter((m) => !mine || m.creator_id === userId), [data, mine, userId]);
  const clusters = useMemo(() => (data?.clusters || [])
    .filter((c) => !mine || c.creator_id === userId), [data, mine, userId]);
  const normalized = query.trim().toLocaleLowerCase();
  const visibleClusters = clusters.filter((c) =>
    `${c.name} ${c.external_name} ${c.machine_name}`.toLocaleLowerCase().includes(normalized) &&
    (!issuesOnly || !["healthy", "archived"].includes(clusterHealth(c, now))),
  ).sort((a, b) => priority[clusterHealth(a, now)] - priority[clusterHealth(b, now)] || a.name.localeCompare(b.name, "zh-CN"));
  const visibleMachines = machines.filter((m) =>
    `${m.name} ${m.address} ${m.ip}`.toLocaleLowerCase().includes(normalized) &&
    (!issuesOnly || !["healthy", "archived"].includes(machineHealth(m, now))),
  ).sort((a, b) => {
    if (sort) {
      const value = (m: Machine) => {
        const usage = currentUsage(m, now);
        if (!usage) return null;
        if (sort.field === "cpu") return usage.cpu_percent;
        if (sort.field === "memory") return usage.memory_total_bytes > 0 ? usage.memory_used_bytes * 100 / usage.memory_total_bytes : null;
        return usage.disks.length ? Math.max(...usage.disks.map((disk) => disk.percent)) : null;
      };
      const av = value(a), bv = value(b);
      if (av == null && bv != null) return 1;
      if (bv == null && av != null) return -1;
      if (av != null && bv != null && av !== bv) return sort.descending ? bv - av : av - bv;
    }
    return priority[machineHealth(a, now)] - priority[machineHealth(b, now)] || a.name.localeCompare(b.name, "zh-CN");
  });
  const issues = [
    ...clusters.filter((c) => ["critical", "warning"].includes(clusterHealth(c, now)))
      .map((c) => ({ key: `c-${c.id}`, name: c.name, state: clusterHealth(c, now),
        message: reason(c.last_error) || `${c.running_instances ?? "—"}/${c.expected_instances ?? "—"} 个服务实例运行`,
        href: `#/clusters/${encodeURIComponent(c.id)}` })),
    ...machines.filter((m) => ["critical", "warning"].includes(machineHealth(m, now)))
      .map((m) => ({ key: `m-${m.id}`, name: m.name, state: machineHealth(m, now),
        message: fullDisks(m, now).length
          ? `磁盘空间不足：${fullDisks(m, now).map((disk) => `${disk.mountpoint} 已用 ${Number(disk.percent.toFixed(2))}%，剩余 ${bytes(disk.total_bytes - disk.used_bytes)}`).join("；")}`
          : reason(m.probe?.error || m.probe?.usage_error) || "SSH 检查异常", href: `#/machines/${encodeURIComponent(m.id)}` })),
  ].sort((a, b) => priority[a.state] - priority[b.state]).slice(0, 6);
  const unknownCount = clusters.filter((c) => clusterHealth(c, now) === "unknown").length +
    machines.filter((m) => machineHealth(m, now) === "unknown").length;
  const issueCount = clusters.filter((c) => ["critical", "warning"].includes(clusterHealth(c, now))).length +
    machines.filter((m) => ["critical", "warning"].includes(machineHealth(m, now))).length;
  const pageCount = Math.max(1, Math.ceil(visibleMachines.length / 15));
  const safePage = Math.min(page, pageCount - 1);
  const names = new Map((data?.clusters || []).map((c) => [c.id, c.name]));
  return <div className="dashboard-page">
    <header className="page-header dashboard-heading">
      <div><p className="eyebrow">PLATFORM / OVERVIEW</p><h1>资源总览</h1>
        <p className="muted">查看机器连接和集群服务状态。服务在线不代表业务读写已验证。</p></div>
      <button className="primary" disabled={refreshing || data?.progress.running} onClick={() => void refresh()}>
        {refreshing ? "正在请求…" : data?.progress.running ? "检查中" : "刷新状态"}
      </button>
    </header>
    <div className="dashboard-toolbar">
      <label>查看范围<select aria-label="查看范围" value={mine ? "mine" : "all"} onChange={(e) => { setMine(e.target.value === "mine"); setPage(0); }}>
        <option value="all">全部资源</option><option value="mine">我的资源</option>
      </select></label>
      <label>搜索资源<input aria-label="搜索资源" type="search" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} placeholder="名称、IP 或集群" /></label>
      <label className="dashboard-checkbox"><input type="checkbox" checked={issuesOnly} onChange={(e) => { setIssuesOnly(e.target.checked); setPage(0); }} />只看需关注</label>
      <span className="muted">页面更新：{data ? age(data.generated_at, now) : "—"}</span>
    </div>
    {loading && !data && <p role="status">正在读取资源状态…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {data?.progress.running && <p role="status" className="dashboard-progress">正在检查资源 {data.progress.completed} / {data.progress.total}</p>}
    {data?.progress.error && <p role="alert" className="error">{data.progress.error}</p>}
    {data && <>
      <div className="dashboard-stats">
        <Stat label="集群" value={clusters.length} detail={`${clusters.filter((c) => clusterHealth(c, now) === "healthy").length} 个服务全部运行`} />
        <Stat label="机器" value={machines.length} detail={`${machines.filter((m) => machineHealth(m, now) === "healthy").length} 台最近可连接`} />
        <Stat label="需要关注" value={issueCount} detail={`${unknownCount} 项状态待确认`} />
      </div>
      <section className="panel dashboard-attention" aria-label="需要关注">
        <div className="dashboard-section-heading"><h2>需要关注</h2><span className="muted">优先显示明确异常</span></div>
        {issues.length ? <ul>{issues.map((item) => <li key={item.key}><HealthBadge state={item.state} />
          <a href={item.href}>{item.name}</a><span>{item.message}</span><a href={item.href}>查看详情</a></li>)}</ul>
          : <p className="muted">当前没有明确异常。{unknownCount ? `另有 ${unknownCount} 项状态待确认。` : ""}</p>}
      </section>
      <section aria-label="集群概览" className="dashboard-section">
        <div className="dashboard-section-heading"><h2>集群概览</h2><a href="#/clusters">查看全部集群 ›</a></div>
        <div className="dashboard-clusters">
          {visibleClusters.map((c) => {
            const state = clusterHealth(c, now);
            return <article className={`dashboard-cluster dashboard-cluster-${state}`} key={c.id}>
              <div className="dashboard-cluster-top"><div><small>{c.external_name}</small><h3><a href={`#/clusters/${encodeURIComponent(c.id)}`}>{c.name}</a></h3></div><HealthBadge state={state} /></div>
              <p className="dashboard-cluster-count"><strong>{c.running_instances ?? "—"}</strong> / {c.expected_instances ?? "—"} 个服务实例运行</p>
              <div className="dashboard-roles">{Object.entries(c.roles).map(([role, count]) =>
                <a key={role} href={`#/clusters/${encodeURIComponent(c.id)}`} className={count.running < count.expected ? "dashboard-role-alert" : ""}>
                  {role} {count.running}/{count.expected}</a>)}
                {!Object.keys(c.roles).length && <span className="muted">服务明细尚未采集</span>}</div>
              <p className="dashboard-cluster-note">{reason(c.last_error) || (state === "unknown" ? "状态未检查或已过期" : "业务读写：未验证")}</p>
              <div className="dashboard-cluster-footer"><span>{c.machine_name} · {c.os_user}</span><span title={c.last_attempt_at || ""}>{age(c.last_attempt_at, now)}</span></div>
              <div className="dashboard-cluster-actions"><a className="dashboard-main-action" href={`#/clusters/${encodeURIComponent(c.id)}/resources`}>资源管理</a>
                <a href={`#/clusters/${encodeURIComponent(c.id)}`}>集群详情</a>
                {c.services[0]?.id && <a href={`#/clusters/${encodeURIComponent(c.id)}/logs/${encodeURIComponent(c.services[0].id)}`}>异常服务日志</a>}</div>
            </article>;
          })}
          {!visibleClusters.length && <p className="muted">没有符合筛选条件的集群。</p>}
        </div>
      </section>
      <section aria-label="机器概览" className="dashboard-section">
        <div className="dashboard-section-heading"><h2>机器概览</h2><a href="#/machines">查看全部机器 ›</a></div>
        <div className="dashboard-table-scroll"><table className="dashboard-table"><thead><tr>
          <th>状态</th><th>机器资源</th><th>IP</th><th>CPU 配置</th><th>内存总量</th><th>磁盘总量</th>
          {([['cpu', 'CPU 占用率'], ['memory', '内存占用率'], ['disk', '磁盘占用率']] as const).map(([field, title]) =>
            <th key={field}><button className="dashboard-sort" onClick={() => setSort(sort?.field === field
              ? { field, descending: !sort.descending } : { field, descending: true })}>{title}{sort?.field === field ? (sort.descending ? ' ↓' : ' ↑') : ''}</button></th>)}
          <th>网络 / RDMA</th><th>关联集群</th><th>最近检查</th>
        </tr></thead><tbody>{visibleMachines.slice(safePage * 15, (safePage + 1) * 15).map((m) => {
          const usage = currentUsage(m, now);
          const disks = usage?.disks.slice().sort((a, b) => b.percent - a.percent) || [];
          const peak = disks[0];
          const fullCount = fullDisks(m, now).length;
          const memoryPercent = usage && usage.memory_total_bytes > 0
            ? usage.memory_used_bytes * 100 / usage.memory_total_bytes : null;
          return <Fragment key={m.id}><tr>
            <td><HealthBadge state={machineHealth(m, now)} /></td>
            <th scope="row"><a href={`#/machines/${encodeURIComponent(m.id)}`}>{m.name}</a>
              {(m.probe?.error || m.probe?.usage_error) && <small>{reason(m.probe.error || m.probe.usage_error)}</small>}</th>
            <td>{m.ip || m.address}</td><td title={m.cpu_model || ""}>{m.cpu_model || "—"}<small>{m.physical_cores ?? "—"}/{m.logical_cores ?? "—"} 核</small></td>
            <td>{m.memory_bytes != null ? bytes(m.memory_bytes) : "—"}</td><td>{m.disk_bytes != null ? bytes(m.disk_bytes) : "—"}</td>
            <td><PercentBar value={usage?.cpu_percent ?? null} /></td>
            <td><PercentBar value={memoryPercent} />{usage && <small>{bytes(usage.memory_used_bytes)} / {bytes(usage.memory_total_bytes)}</small>}</td>
            <td><PercentBar value={peak?.percent ?? null} alert={fullCount > 0} />
              {peak && <small>{peak.mountpoint} · 剩余 {bytes(peak.total_bytes - peak.used_bytes)}</small>}
              {fullCount > 0 && <small className="dashboard-disk-warning">{fullCount} 个磁盘超过 90%</small>}
              {disks.length > 0 && <button className="dashboard-detail-button" aria-label={`${expanded === m.id ? "收起" : "查看"} ${m.name} 的磁盘明细`}
                onClick={() => setExpanded(expanded === m.id ? null : m.id)}>{expanded === m.id ? "收起明细" : "查看明细"}</button>}</td>
            <td>{m.max_speed_mbps ? `${m.max_speed_mbps} Mbps` : "—"}<small>RDMA {m.rdma_devices?.length ?? "—"}</small></td>
            <td>{m.cluster_ids.length ? m.cluster_ids.map((id) => <a key={id} href={`#/clusters/${encodeURIComponent(id)}`}>{names.get(id) || id}</a>) : "—"}</td>
            <td title={m.probe?.checked_at || ""}>{age(m.probe?.checked_at, now)}</td>
          </tr>{expanded === m.id && <tr className="dashboard-detail-row"><td colSpan={12}>
            <div className="dashboard-disk-detail"><strong>{m.name} 的本地磁盘</strong>
              <table><thead><tr><th>挂载目录</th><th>设备</th><th>占用率</th><th>已用 / 总量</th><th>剩余</th></tr></thead>
                <tbody>{disks.map((disk) => <tr key={disk.mountpoint}><td>{(disk.mountpoints || [disk.mountpoint]).map((path) => <div key={path}>{path}</div>)}</td><td>{disk.device}</td>
                  <td><PercentBar value={disk.percent} alert={disk.total_bytes > 0 && disk.used_bytes / disk.total_bytes > 0.9} /></td>
                  <td>{bytes(disk.used_bytes)} / {bytes(disk.total_bytes)}</td><td>{bytes(disk.total_bytes - disk.used_bytes)}</td></tr>)}</tbody></table>
            </div></td></tr>}</Fragment>;
        })}</tbody></table></div>
        {!visibleMachines.length && <p className="muted">没有符合筛选条件的机器。</p>}
        {pageCount > 1 && <div className="dashboard-pagination"><button disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>上一页</button>
          <span>{safePage + 1} / {pageCount}</span><button disabled={safePage + 1 >= pageCount} onClick={() => setPage(safePage + 1)}>下一页</button></div>}
      </section>
    </>}
  </div>;
}
