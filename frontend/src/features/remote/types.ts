export type RemoteTarget = {
  machine_id: string;
  name: string;
  address: string;
  ssh_port?: number;
  ssh_user: string;
  service_ids: string[];
  can_read_logs: boolean;
};
export type RemoteService = {
  id: string;
  role: string;
  host: string;
  log_dir: string;
  machine_id: string | null;
  can_read_logs: boolean;
  match_state: "matched" | "missing" | "ambiguous";
};
export type RemoteTargets = {
  items: RemoteTarget[];
  services: RemoteService[];
};
export type Cursor = { device: number; inode: number; offset: number };
export type RemoteFile = {
  file_id: string;
  name: string;
  size: number;
  mtime: number | string;
};
export type SearchHit = { name: string; line: number; text: string; before: string[]; after: string[] };
export type RemoteKind =
  "files" | "search" | "read" | "download" | "log-follow" | "terminal";
export type RemoteSession = {
  id: string;
  kind: RemoteKind;
  state:
    | "pending"
    | "connecting"
    | "needs_password"
    | "needs_trust"
    | "ready"
    | "running"
    | "succeeded"
    | "failed"
    | "closed"
    | "interrupted";
  machine_id: string;
  machine_name: string;
  address: string;
  ssh_user: string;
  target_user: string;
  cluster_id: string;
  service_id?: string | null;
  log_dir?: string | null;
  expires_at: string;
  challenge?: string | null;
  auth_account?: string | null;
  error_code?: string | null;
  message?: string | null;
  result?: {
    files?: RemoteFile[];
    hits?: SearchHit[];
    progress?: { scanned_files: number; scanned_bytes: number; hits: number };
    scanned_files?: number;
    scanned_bytes?: number;
    skipped_files?: number;
    reason?: string | null;
    text?: string;
    cursor?: Cursor;
    reset?: boolean;
    truncated?: boolean;
  } | null;
};
export type RemoteRequest = {
  kind: RemoteKind;
  cluster_id: string;
  service_id?: string;
  machine_id?: string;
  file_id?: string;
  keyword?: string;
  case_sensitive?: boolean;
  lines?: 100 | 500 | 1000;
  cursor?: Cursor;
  cols?: number;
  rows?: number;
  confirmed?: boolean;
};
export type StreamText = {
  type: "text";
  text: string;
  cursor?: Cursor;
  reset?: boolean;
};
export function logAccessReason(service?: RemoteService) {
  if (!service) return "最近成功的状态中没有这个服务，请返回集群详情刷新状态。";
  if (service.match_state === "missing")
    return "未匹配机器资源，请为对应机器登记服务主机别名。";
  if (service.match_state === "ambiguous")
    return "匹配冲突：多个机器资源使用该主机标识，请调整机器地址或别名。";
  if (!service.log_dir) return "该服务未提供日志目录，请刷新集群状态。";
  if (!service.can_read_logs)
    return "仅管理员，或同时为集群和目标机器创建者的成员可以读取日志。";
  return "";
}
export function sizeText(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
