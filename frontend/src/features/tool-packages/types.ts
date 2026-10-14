export type ToolPackage = {
  id: string;
  tool: string;
  version: string;
  architecture: string;
  directory: string;
  digest: string;
  size_bytes: number;
};
export type ToolStatus = {
  tool: string;
  status: string;
  path: string | null;
  version: string;
  details: string;
};
export type ToolJob = {
  action?: "check" | "install" | "auto_install";
  error_message?: string;
  id: string;
  state: string;
  phase: string;
  progress: number;
  log: string;
  created_at: string;
  result?: {
    error_message?: string;
    command_path?: string;
    method?: string;
    cached?: boolean;
    image_id?: string;
    items: ToolStatus[];
    user?: string;
    architecture?: string;
  };
};
export const toolLabels: Record<string, string> = {
  dtt: "dtt（含 fio、elbencho）",
  dingo: "dingo",
  "dingo-client": "dingo-client",
  "dingo-cache": "dingo-cache",
};
