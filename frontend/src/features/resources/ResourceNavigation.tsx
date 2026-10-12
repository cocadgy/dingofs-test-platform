import { cacheGroupResources } from "./cacheGroupResources";
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
  let cacheCount: number | string = "—";
  const latest = snapshot.operations.find(
    (item) => item.action === "cache.list",
  );
  if (latest?.state === "succeeded") {
    try {
      cacheCount = cacheGroupResources(
        latest,
        snapshot.resources,
        undefined,
        snapshot.operations,
      ).length;
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
          {item.key !== "filesystem" && (
            <span>
              {item.key === "history"
                ? operationCount
                : item.key === "cache"
                  ? cacheCount
                  : snapshot.resources.filter(
                      (resource) => resource.kind === item.key,
                    ).length}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
