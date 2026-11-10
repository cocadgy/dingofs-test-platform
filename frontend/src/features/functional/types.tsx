
export type ManagementMachine = {id:string;name:string;address:string;ssh_user:string};
export type GuidedCluster = {id:string;name:string;mds_addresses:string[];management_machine:ManagementMachine;available:boolean};
export type GuidedMachine = ManagementMachine & {aliases:string[];available:boolean};
export type GuidedMetadata = {enabled:boolean;clusters:GuidedCluster[];machines?:GuidedMachine[]};
export type EnvironmentDescriptor = {
  env_name:string;source_manifest:Record<string,string>;digest:string;
  mds_addresses:string[];targets:{role:string;host:string;user:string;mutates:boolean;name?:string;address?:string}[];
  client_count:number|null;cache_count:number|null;storage_type:string|null;
  programs:Record<string,unknown>;directories:Record<string,unknown>;
  modules:Record<string,{available:boolean;reasons:string[];impacts:string[];fixed_resources?:string[]}>;
  issues:string[];
};
export type GuidedModulePlan = {
  module:string;environment_profile_id:string;environment_profile_revision:number;cases:string[];
};
export type GuidedConfiguration = {
  kind:"existing-environments";version:2;cluster_id:string;default_environment_id:string;
  module_plans:GuidedModulePlan[];name:string;retries:number;timeout_minutes:number;
};
export type GuidedCompatibility = {modules:Record<string,{
  compatible:boolean;reasons:string[];impacts:string[];
  targets?:EnvironmentDescriptor["targets"]}>};
export type GuidedPreflight = {
  can_start:boolean;token:string|null;expires_at:string|null;
  checks:{code:string;ok:boolean;host?:string;user?:string;conflicts?:{key:string;reason:string}[]}[];
  required_confirmations:string[];impacts:{module?:string;description:string}[];
};
export type Case = {
  path: string;
  id?: string;
  name: string;
  run_level?: string;
  description?: string;
};
export type Options = {
  digest: string;
  modules: Record<string, Case[]>;
  machines?: {id:string;name:string;address:string;ssh_user:string}[];
  clusters: {
    id: string;
    name: string;
    machine: string;
    mds_addresses?: string[];
  }[];
};
export type Profile = {
  id: string;
  name: string;
  revision: number;
  enabled: boolean;
  source_kind: string;
  source_file?: string;
  source_key?: string;
  source_digest?: string;
  cluster_id: string | null;
  validation: string;
  machine_id?: string;
  settings?: {
    binaries?: Record<string, string>;
    clients?: {
      machine_id: string;
      client_count: number;
      mount_path?: string;
    }[];
    remote_caches?: { machine_id: string; remote_cache_count: number }[];
    mount_root?: string;
  };
  display?: {
    mds_addresses?: string[];
    client_hosts?: string[];
    client_count?: number;
    cache_count?: number;
    storage_type?: string;
    machine_name?: string;
    storage_name?: string;
    base?: string;
    issue?: string;
    template?: boolean;
    descriptor?: EnvironmentDescriptor;
  };
};
export type MachineIdentity = { machine_id: string; name: string; ip: string; user: string };
export type FunctionalEventV2 = {
  version: 2; seq: number; time: string; type: string; stage: string;
  parent_id: string; child_id: string; module: string;
  case_path: string | null; attempt: number | null; data: Record<string, unknown>;
};
export type ChildResult = {
  child_state: string; stage: string;
  case_counts: { passed: number; failed: number; skipped: number; known_bugs: number; completed: number; total: number };
  case_results: { case_path: string; attempt: number; status: string }[];
  attempt_records: { case_path: string; attempt: number; status: string; seq: number }[];
  failed_cases: string[]; missing: string[]; not_run: string[]; suite_errors: number;
  cleanup_status: string; recovery_status: string;
  retained_resources: { id: string; kind: string; cluster: string; host: string | null;
    user: string | null; name: string | null; path: string | null; port: number | null;
    owned: boolean; phase: string; remote_identity: Record<string, unknown> }[];
  report_status: "pending" | "missing" | "failed" | "ready";
  report_path: string | null; may_continue: boolean; end_proof: boolean;
};
export type ModuleRunView = {
  id: string; module: string; position: number; env_name: string; state: string;
  stage: string; execution_targets: MachineIdentity[]; events: FunctionalEventV2[];
  environment_snapshot: Record<string, unknown>; cases: string[];
  started_at: string | null; deadline: string | null; finished_at: string | null;
  // A newly queued child is currently returned with {} until its first observation.
  result: Partial<ChildResult>; error: string;
};
export function verifiedCaseCounts(child: ModuleRunView): ChildResult["case_counts"] | null {
  const counts = child.result?.case_counts;
  const rows = child.result?.case_results;
  const failedCases = child.result?.failed_cases;
  const missing = child.result?.missing;
  const notRun = child.result?.not_run;
  if (!counts || !Array.isArray(rows) || !Array.isArray(failedCases) ||
      !Array.isArray(missing) || !Array.isArray(notRun) ||
      !Array.isArray(child.cases) || new Set(child.cases).size !== child.cases.length) return null;
  const keys = ["passed", "failed", "skipped", "known_bugs", "completed", "total"] as const;
  if (keys.some((key) => !Number.isSafeInteger(counts[key]) || counts[key] < 0) ||
      counts.total !== child.cases.length || counts.completed !== rows.length ||
      counts.passed + counts.failed + counts.skipped + counts.known_bugs !== counts.completed ||
      counts.completed + missing.length + notRun.length !== counts.total) return null;
  const selected = new Set(child.cases);
  const seen = new Set<string>();
  const actual = { passed: 0, failed: 0, skipped: 0, known_bugs: 0 };
  const failedPaths: string[] = [];
  const categories = { PASS: "passed", FAIL: "failed", SKIP: "skipped", KNOWN_BUG: "known_bugs" } as const;
  for (const row of rows) {
    if (!selected.has(row.case_path) || seen.has(row.case_path) || !(row.status in categories)) return null;
    seen.add(row.case_path);
    actual[categories[row.status as keyof typeof categories]] += 1;
    if (row.status === "FAIL") failedPaths.push(row.case_path);
  }
  for (const path of [...missing, ...notRun]) {
    if (!selected.has(path) || seen.has(path)) return null;
    seen.add(path);
  }
  return (Object.keys(actual) as (keyof typeof actual)[]).every((key) => actual[key] === counts[key]) &&
    failedCases.length === failedPaths.length && failedCases.every((path) => failedPaths.includes(path))
    ? counts : null;
}
export type Run = {
  id: string;
  name: string;
  state: string;
  phase: string;
  progress: number;
  version?: number;
  can_manage?: boolean;
  children?: ModuleRunView[];
  error: string;
  log?: string;
  result?: {
    cases?: { module: string; case: string; status: string; time?: string }[];
  };
  snapshot: {
    selected?: Record<string, string[]>;
    cluster_id?: string;
    cluster_name?: string;
    environment_name?: string;
  };
  created_at: string;
  finished_at?: string;
};
export const active = (state: string) =>
  ["queued", "running", "cancelling", "unknown", "needs_attention"].includes(state);
export const stateLabels: Record<string, string> = {
  queued: "等待执行",
  running: "运行中",
  cancelling: "正在停止",
  unknown: "状态待确认",
  needs_attention: "需要人工处理",
  success: "通过",
  failed: "失败",
  cancelled: "已停止",
};
export const moduleLabels: Record<string, string> = {
  basic_file_operation: "基础文件操作",
  quota: "配额",
  client: "客户端",
  cache_node: "缓存节点",
  fault: "故障测试",
  posix: "POSIX 兼容性",
  large_scale: "大规模测试",
  large_scale_cache: "大规模缓存",
  mount_subdir: "子目录挂载",
  trash: "回收站",
  dirstat: "目录统计",
  hot_upgrade: "热升级",
  xattr: "扩展属性",
  warmup: "预热",
  mds_manage: "MDS 管理",
};
export function Status({ state }: { state: string }) {
  return (
    <span className={`functional-badge state-${state}`}>
      {stateLabels[state] || state}
    </span>
  );
}
export function elapsed(run: Run) {
  const seconds = Math.max(
    0,
    Math.floor(
      ((run.finished_at ? Date.parse(run.finished_at) : Date.now()) -
        Date.parse(run.created_at)) /
        1000,
    ),
  );
  return Number.isFinite(seconds)
    ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
    : "—";
}
