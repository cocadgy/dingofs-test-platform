import type { CacheProfile, CacheCatalog } from "../cache-profiles/types";
import type { StorageProfile } from "../storage/types";
export type ResourceSection = "filesystem" | "cache" | "mount";
export type Parameters = Record<string, unknown>;
export type ResourceField = {
  key: string;
  label: string;
  type:
    | "text"
    | "number"
    | "boolean"
    | "password"
    | "select"
    | "members"
    | "names"
    | "cache_options" | "mount_options";
  required?: boolean;
  default?: unknown;
  options?: string[];
  fields?: ResourceField[];
};
export type ResourceAction = {
  action: string;
  label: string;
  section: ResourceSection;
  mutating: boolean;
  fields: ResourceField[];
};
export type ResourceMachine = {
  id: string;
  name: string;
  address: string;
  ssh_user: string;
  can_manage: boolean;
};
export type SavedResource = {
  id: string;
  kind: "cache" | "mount";
  name: string;
  state: string;
  data: Parameters;
  created_at: string;
};
export type ResourceOperation = {
  id: string;
  action: string;
  state: string;
  payload?: Parameters;
  result?: {
    steps?: {
      fs_name?: string;
      member_id?: string;
      message?: string | null;
      failed?: boolean;
      stdout?: string;
      stderr?: string;
      returncode?: number | null;
      data?: unknown;
    }[];
    [key: string]: unknown;
  } | null;
  phase?: string | null;
  error_code?: string | null;
  message?: string | null;
  auth_account?: string;
  challenge?: string;
  target_user?: string;
  machine_name?: string;
  creator_id?: string;
  created_at?: string;
};
export type CacheMemberTarget = {
  machine_id?: string | null;
  machine_name?: string | null;
  target_user?: string;
  can_stop: boolean;
  reason?: string | null;
};
export type ResourceSnapshot = {
  cache_member_targets?: Record<string, CacheMemberTarget>;
  storage_profiles?: StorageProfile[];
  mount_profiles?: CacheProfile[];
  mount_parameter_catalog?: CacheCatalog;
  cache_profiles?: CacheProfile[];
  cache_parameter_catalog?: CacheCatalog;
  catalog: ResourceAction[];
  machines: ResourceMachine[];
  resources: SavedResource[];
  operations: ResourceOperation[];
};
export const pendingStates = [
  "pending",
  "running",
  "needs_password",
  "needs_trust",
];
export const stateLabels: Record<string, string> = {
  pending: "等待执行",
  running: "执行中",
  needs_password: "等待用户切换认证",
  needs_trust: "需要核验 SSH 指纹",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消等待",
  interrupted: "结果待核实",
  unknown: "结果未知",
  partial: "部分完成，需核实",
  mounted: "已挂载",
  unmounted: "已卸载",
  stopped: "已停止",
  cache_empty: "无成员",
  planned: "待确认",
  deleted: "已删除",
};
export const newMember = (field?: ResourceField): Parameters => ({
  machine_id: "",
  target_user: "",
  listen_ip: "",
  listen_port: 21000,
  cache_dir: "",
  cache_size_mb: 1024,
  use_rdma: false,
  rdma_device: "",
  rdma_port: 1,
  ...Object.fromEntries(
    (field?.fields || [])
      .filter((item) => item.default != null)
      .map((item) => [item.key, item.default]),
  ),
  port_mode: "auto",
});
export function defaults(action: ResourceAction): Parameters {
  return Object.fromEntries(
    action.fields.map((field) => [
      field.key,
      field.default ??
        (field.type === "members"
          ? [newMember(field)]
          : field.type === "boolean"
            ? false
            : ""),
    ]),
  );
}
