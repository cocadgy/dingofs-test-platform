export type DiskUsage = { mountpoint: string; mountpoints?: string[]; device: string; used_bytes: number; total_bytes: number; percent: number };
export type Usage = { cpu_percent: number | null; memory_used_bytes: number; memory_total_bytes: number; disks: DiskUsage[] };
export type Probe = { state: string; error: string | null; checked_at: string;
  usage?: Usage | null; usage_error?: string | null } | null;
export function currentUsage(machine: Machine, now = Date.now()): Usage | null {
  return machine.probe && fresh(machine.probe.checked_at, now) && machine.probe.state === "healthy"
    ? machine.probe.usage || null : null;
}
export function fullDisks(machine: Machine, now = Date.now()): DiskUsage[] {
  return (currentUsage(machine, now)?.disks || []).filter((disk) => disk.total_bytes > 0 && disk.used_bytes / disk.total_bytes > 0.9)
    .sort((a, b) => b.percent - a.percent);
}
export type Machine = {
  id: string; name: string; address: string; ip: string; archived: boolean;
  creator_id: string | null; maintenance: boolean; collection_status: string;
  cpu_model: string | null; physical_cores: number | null; logical_cores: number | null;
  memory_bytes: number | null; disk_bytes: number | null; max_speed_mbps: number | null;
  rdma_devices: string[] | null; info_updated_at: string | null;
  cluster_ids: string[]; probe: Probe;
};
export type Cluster = {
  id: string; name: string; external_name: string; creator_id: string | null;
  archived: boolean; binding_state: string; management_machine_id: string;
  machine_name: string; os_user: string; state: string;
  last_success_at: string | null; last_attempt_at: string | null; last_error: string | null;
  service_count: number | null; running_instances: number | null; expected_instances: number | null;
  roles: Record<string, { running: number; expected: number }>;
  services: { id: string; role: string; state: string }[];
};
export type Dashboard = {
  machines: Machine[]; clusters: Cluster[]; generated_at: string;
  progress: { running: boolean; completed: number; total: number; error?: string | null };
};
export type Health = "healthy" | "critical" | "warning" | "unknown" | "maintenance" | "archived";
export const STALE_MS = 5 * 60_000;
export function fresh(value: string | null | undefined, now = Date.now()) {
  if (!value) return false;
  const age = now - Date.parse(value);
  return Number.isFinite(age) && age >= -60_000 && age <= STALE_MS;
}
export function machineHealth(machine: Machine, now = Date.now()): Health {
  if (machine.archived) return "archived";
  if (machine.maintenance) return "maintenance";
  if (!machine.probe || !fresh(machine.probe.checked_at, now)) return "unknown";
  if (machine.probe.state === "healthy") {
    if (machine.probe.usage_error || fullDisks(machine, now).length) return "warning";
    return "healthy";
  }
  if (["connection_failed", "timeout"].includes(machine.probe.error || "")) return "critical";
  return "warning";
}
export function clusterHealth(cluster: Cluster, now = Date.now()): Health {
  if (cluster.archived) return "archived";
  if (!fresh(cluster.last_attempt_at, now)) return "unknown";
  if (["pending", "running"].includes(cluster.last_error || "")) return "unknown";
  if (cluster.last_error) return "warning";
  if (cluster.state === "running") return "healthy";
  if (["degraded", "stopped"].includes(cluster.state)) return "critical";
  return "unknown";
}
export const priority: Record<Health, number> = {
  critical: 0, warning: 1, unknown: 2, maintenance: 3, healthy: 4, archived: 5,
};
export const label: Record<Health, string> = {
  healthy: "正常", critical: "异常", warning: "待处理", unknown: "待确认",
  maintenance: "维护中", archived: "已归档",
};
export const errorText: Record<string, string> = {
  authentication_failed: "SSH 认证失败", connection_failed: "SSH 连接失败",
  timeout: "连接超时", worker_failed: "检查失败", needs_password: "切换用户需要密码",
  credential_unavailable: "SSH 凭据不可用", query_failed: "集群状态查询失败",
  invalid_header: "无法解析集群状态", invalid_row: "服务列表解析失败",
  invalid_identity: "执行用户校验失败", switch_denied: "无法切换执行用户",
  dingo_missing: "未找到 dingo 命令", pending: "等待检查", running: "正在检查",
  needs_trust: "SSH 指纹需要确认", interrupted: "检查中断",
  invalid_metrics: "资源占用采集失败",
};
export function reason(value: string | null | undefined) {
  return value ? errorText[value] || value : "";
}
