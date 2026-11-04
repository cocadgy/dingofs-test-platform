import { cacheGroupResources } from "./cacheGroupResources";
import { useRef } from "react";
import { filesystemOptions, visibleFilesystemName } from "./filesystemOptions";
import type { ResourceSnapshot } from "./types";
import { sections, type ResourceArea } from "./workspace";

export function ResourceNavigation({
  area,
  snapshot,
  operationCount,
  onChange,
}: {
  area: ResourceArea;
  snapshot: ResourceSnapshot;
  operationCount: number;
  onChange: (area: ResourceArea) => void;
}) {
  // Never present a previous visit's successful query as current inventory.
  const historical = useRef(new Set(snapshot.operations.map((item) => item.id)));
  const fresh = (action: string) => snapshot.operations.find(
    (item) => item.action === action && !historical.current.has(item.id),
  );
  let filesystemCount: number | string = "—";
  let mountCount: number | string = "—";
  const filesystems = fresh("fs.list");
  if (filesystems?.state === "succeeded") {
    try {
      filesystemCount = filesystemOptions(filesystems).length;
      for (const step of filesystems.result?.steps || []) {
        const data = step.data ?? (step.stdout ? JSON.parse(step.stdout) : undefined);
        const rows = Array.isArray(data) ? data : (data?.result ?? data)?.fs_infos;
        if (!Array.isArray(rows)) continue;
        let total = 0;
        for (const row of rows) {
          if (!visibleFilesystemName(row.fs_name)) continue;
          const mounts = row.mount_points ?? row.mountPoints ?? [];
          if (!Array.isArray(mounts)) throw new Error("Invalid mount points");
          total += mounts.length;
        }
        mountCount = total;
        break;
      }
    } catch { /* Unknown is not zero; never fall back to saved records. */ }
  }
  let cacheCount: number | string = "—";
  const latest = fresh("cache.list");
  if (latest?.state === "succeeded") {
    try {
      cacheCount = cacheGroupResources(
        latest,
        snapshot.resources,
        undefined,
        snapshot.operations,
      ).filter((group) => Number(group.data.online_count) > 0).length;
    } catch {
      /* A malformed query must not become a count of local attempts. */
    }
  }
  return (
    <nav className="resource-primary-nav" aria-label="资源功能">
      {[
        ...sections.map((section) => ({
          key: section.key,
          label: section.key === "mount" ? "挂载点" : section.label,
        })),
        { key: "history", label: "操作记录" },
      ].map((item) => (
        <button
          key={item.key}
          type="button"
          aria-current={area === item.key ? "page" : undefined}
          onClick={() => onChange(item.key as ResourceArea)}
        >
          {item.label}
            <span title={item.key === "mount" ? "集群当前返回的挂载点数量（MDS 注册信息）" : item.key === "cache" ? "至少有一个在线成员的缓存组" : undefined}>
              {item.key === "history"
                ? operationCount
                : item.key === "cache"
                  ? cacheCount
                  : item.key === "filesystem" ? filesystemCount : mountCount}
            </span>
        </button>
      ))}
    </nav>
  );
}
