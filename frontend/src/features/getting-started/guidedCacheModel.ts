import type { CapacityUnit } from "./CapacityInput";
import type { CacheOptions } from "../cache-profiles/types";
import type { Parameters, ResourceMachine } from "../resources/types";
import type { FilesystemSuffix } from "./filesystemName";

export type CacheMachineDraft = {
  machineId: string; user: string; count: number; directory: string; capacity: number; capacityUnit?: CapacityUnit;
  listenIp: string; portMode: "auto" | "manual"; port: number;
  binaryDirectory: string; rdma: boolean; rdmaDevice: string; rdmaPort: number;
};
export type CacheDraft = {
  clusterId: string; name: string; suffix: FilesystemSuffix; profileId: string;
  source: "default" | "tag" | "path"; tag: string; imageDigest: string; binaryDirectory: string;
  options?: CacheOptions;
  rows: CacheMachineDraft[];
};
export const blankCacheDraft = (): CacheDraft => ({
  clusterId: "", name: "", suffix: "none", profileId: "", source: "default",
  tag: "", imageDigest: "", binaryDirectory: "", rows: [],
});
export function newCacheRow(machine: ResourceMachine): CacheMachineDraft {
  return { machineId: machine.id, user: machine.ssh_user, count: 1, directory: "", capacity: 1024,
    listenIp: machine.address, portMode: "auto", port: 21000, binaryDirectory: "",
    rdma: false, rdmaDevice: "", rdmaPort: 1 };
}
export function cacheDraftError(draft: CacheDraft): string {
  if (draft.source === "tag" && (!draft.tag || !/^sha256:[0-9a-f]{64}$/.test(draft.imageDigest))) return "请从列表选择镜像 TAG";
  if (!draft.rows.length) return "请至少选择一台部署机器";
  for (const row of draft.rows) {
    if (!row.user.trim() || !row.directory.startsWith("/") || row.directory === "/") return "请填写各机器的执行用户和缓存基础目录";
    if (!Number.isInteger(row.count) || row.count < 1 || !Number.isSafeInteger(row.capacity) || row.capacity < 1) return "节点数量必须为正整数，容量换算为 MiB 后必须为安全范围内的正整数";
    if (draft.source === "path" && !(row.binaryDirectory || draft.binaryDirectory).startsWith("/")) return "请填写程序所在目录的绝对路径";
    if (row.portMode === "manual" && (!Number.isInteger(row.port) || row.port < 1 || row.port + row.count - 1 > 65535)) return "手动端口范围必须在 1～65535 之间";
    if (row.rdma && !row.rdmaDevice.trim()) return "启用 RDMA 时请填写设备名称";
  }
  return "";
}
export function cacheMembers(draft: CacheDraft): Parameters[] {
  const error = cacheDraftError(draft);
  if (error) throw new Error(error);
  return draft.rows.flatMap(row => Array.from({ length: row.count }, (_, index) => ({
    machine_id: row.machineId, target_user: row.user.trim(),
    listen_ip: row.listenIp.trim(), port_mode: row.portMode, listen_port: row.port + (row.portMode === "manual" ? index : 0),
    cache_dir: row.directory.trim(), cache_size_mb: row.capacity,
    use_rdma: row.rdma, rdma_device: row.rdmaDevice.trim(), rdma_port: row.rdmaPort,
    binary_source: draft.source, binary_tag: draft.source === "tag" ? draft.tag : "",
    binary_digest: draft.source === "tag" ? draft.imageDigest : "",
    binary_directory: draft.source === "path" ? (row.binaryDirectory || draft.binaryDirectory).trim() : "",
  })));
}
