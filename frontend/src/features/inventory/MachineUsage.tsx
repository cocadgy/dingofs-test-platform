import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { currentUsage, fresh, reason, type Dashboard, type Machine } from "../dashboard/health";
import { bytes } from "./MachineHardware";

function Meter({ value, warning = false }: { value: number | null; warning?: boolean }) {
  if (value == null || !Number.isFinite(value)) return <span className="muted">—</span>;
  return <span className="dashboard-meter"><strong>{Number(value.toFixed(2))}%</strong>
    <span className="dashboard-meter-track" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <span className={warning ? "dashboard-meter-fill dashboard-meter-alert" : "dashboard-meter-fill"}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </span></span>;
}

export function MachineUsage({ machineId }: { machineId: string }) {
  const [machine, setMachine] = useState<Machine | null>(null);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await api<Dashboard>("/dashboard");
        if (active) { setMachine(data.machines.find((item) => item.id === machineId) || null); setError(""); setNow(Date.now()); }
      } catch (e) {
        if (active) { setMachine(null); setError((e as Error).message); setNow(Date.now()); }
      } finally { if (active) setLoading(false); }
    };
    setMachine(null); setLoading(true); void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); else setNow(Date.now()); }, 15_000);
    return () => { active = false; clearInterval(timer); };
  }, [machineId]);
  const probe = machine?.probe;
  const usage = machine ? currentUsage(machine, now) : null;
  const disks = [...(usage?.disks || [])].sort((a, b) => b.percent - a.percent);
  const memoryPercent = usage?.memory_total_bytes ? usage.memory_used_bytes / usage.memory_total_bytes * 100 : null;
  const status = error || (loading ? "正在读取资源占用…" : !probe ? "尚未采集资源占用" :
    !fresh(probe.checked_at, now) ? "占用率数据已过期，等待后台重新采集" :
    probe.state !== "healthy" ? reason(probe.error) || "机器状态检查失败" :
    !usage ? reason(probe.usage_error) || "资源占用尚未采集" : "");
  return <section className="machine-usage">
    <h3>当前资源占用</h3>
    <p className="muted">数据来自后台巡检{probe?.checked_at ? `，采集于 ${new Date(probe.checked_at).toLocaleString()}` : ""}。</p>
    {status ? <p role="status">{status}</p> : <>
      <div className="machine-usage-summary">
        <div><span>CPU 占用率</span><Meter value={usage?.cpu_percent ?? null} /></div>
        <div><span>内存占用率</span><Meter value={memoryPercent} /><small>{bytes(usage?.memory_used_bytes)} / {bytes(usage?.memory_total_bytes)}</small></div>
        <div><span>磁盘占用率</span><Meter value={disks[0]?.percent ?? null} warning={!!disks[0] && disks[0].used_bytes / disks[0].total_bytes > 0.9} />
          <small>{disks[0] ? `最高：${disks[0].mountpoint}` : "未发现本地文件系统"}</small></div>
      </div>
      {disks.length > 0 && <div className="hardware-table"><table>
        <thead><tr><th>挂载目录</th><th>设备</th><th>磁盘占用率</th><th>已用 / 总量</th><th>剩余</th><th>状态</th></tr></thead>
        <tbody>{disks.map((disk) => {
          const warning = disk.total_bytes > 0 && disk.used_bytes / disk.total_bytes > 0.9;
          return <tr key={`${disk.device}:${disk.mountpoint}`}>
            <td>{(disk.mountpoints?.length ? disk.mountpoints : [disk.mountpoint]).join("、")}</td><td>{disk.device}</td>
            <td><Meter value={disk.percent} warning={warning} /></td>
            <td>{bytes(disk.used_bytes)} / {bytes(disk.total_bytes)}</td><td>{bytes(disk.total_bytes - disk.used_bytes)}</td>
            <td className={warning ? "dashboard-disk-warning" : ""}>{warning ? "需关注" : "正常"}</td>
          </tr>;
        })}</tbody>
      </table></div>}
    </>}
  </section>;
}
