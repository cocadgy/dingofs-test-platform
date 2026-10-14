export type Tool = "fio" | "elbencho" | "mdtest";
export type MdtestOption = {flag:string;label:string;group:string;kind:string;default:string|number|boolean;choices?:string[];min?:number;bytes?:boolean};
export type Spec = {
  mdtest_options?: Record<string,string|number|boolean>;
  tool: Tool;
  layout?: string;
  direct: boolean;
  concurrency: number;
  file_size: string;
  file_count: number;
  total_size: string;
  block_size: string;
  rw: string;
  rounds: number;
  iodepth: number;
  read_percent: number;
};
export type Options = {
  mdtest_options?: MdtestOption[];
  machines: {
    id: string;
    name: string;
    address: string;
    ssh_user: string;
    maintenance: boolean;
  }[];
  mounts: {
    id: string;
    name: string;
    state: string;
    machine_id: string;
    path: string;
  }[];
};
export type Scenario = { id: string; tool: Tool; parameters: Spec };
export type Report = {
  state?: string;
  error?: string;
  tool?: string;
  parameters?: Spec;
  summary?: {
    status: string;
    error?: string;
    statistics?: {
      successful_rounds: number;
      requested_rounds: number;
      metrics: Record<string, { mean: number | null; samples: number }>;
    };
  };
  remote_path: string;
  command: string;
  files: string[];
};
export type Run = {
  id: string;
  name: string;
  state: string;
  phase: string;
  progress: number;
  error: string;
  log?: string;
  created_at: string;
  finished_at?: string;
  deadline: string;
  can_manage: boolean;
  cancel_requested: boolean;
  remote_root?: string;
  snapshot: {
    cleanup_data?: boolean;
    machine_name: string;
    connection: [string, number, string];
    target_path: string;
    target_kind: string;
    tests: Spec[];
    scenarios?: Scenario[];
  };
  reports: Record<string, Report>;
};
export type Preview = {
  total_bytes: number;
  scene_count?: number;
  tests: { id?: string; tool: string; command: string; mdtest_command?:string; parameters: Spec }[];
};
