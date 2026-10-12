export type CacheOptions = Record<string, string>;
export type CacheParameter = {
  name: string;
  label: string;
  type: string;
  group: string;
  description: string;
  default: string | null;
  managed: string | null;
  member_key: string | null;
  note?: string;
  choices?: string[];
};
export type CacheCatalog = { source_version: string; fields: CacheParameter[] };
export type CacheProfile = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  parameters: CacheOptions;
  revision: number;
  creator_id: string;
  source_version: string;
  can_manage: boolean;
  updated_at: string;
};
export function memberDefaults(options: CacheOptions): Record<string, unknown> {
  const keys: Record<string, string> = {
    id: "member_id",
    cache_dir: "cache_dir",
    cache_size_mb: "cache_size_mb",
    use_rdma: "use_rdma",
    cache_rdma_device: "rdma_device",
    cache_rdma_port_num: "rdma_port",
  };
  return Object.fromEntries(
    Object.entries(options)
      .filter(([key]) => keys[key])
      .map(([key, value]) => [
        keys[key],
        key === "use_rdma"
          ? value === "true"
          : ["cache_size_mb", "cache_rdma_port_num"].includes(key)
            ? Number(value)
            : value,
      ]),
  );
}
