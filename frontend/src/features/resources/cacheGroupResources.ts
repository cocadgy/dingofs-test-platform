import { mergeCacheDeletions } from "./useCacheMemberListing";
import {
  cacheMemberOptions,
  type CacheMemberOption,
} from "./cacheMemberOptions";
import type {
  ResourceOperation,
  SavedResource,
  CacheMemberTarget,
} from "./types";

// The MDS result is the inventory; stop capabilities come from owned records or server-resolved machines.
export function cacheGroupResources(
  operation: ResourceOperation,
  managed: SavedResource[],
  members: CacheMemberOption[] = cacheMemberOptions(operation),
  operations: ResourceOperation[] = [],
  targets: Record<string, CacheMemberTarget> = {},
): SavedResource[] {
  if (operation.state !== "succeeded") return [];
  const originalGroups = new Set(
    cacheMemberOptions(operation).map((member) => member.groupName),
  );
  const deletedAt = mergeCacheDeletions(operations);
  const queriedAt = Date.parse(operation.created_at || "") || 0;
  members = members.filter(
    (member) => (deletedAt.get(member.id) ?? -1) < queriedAt,
  );
  const groups = new Map<string, CacheMemberOption[]>();
  for (const step of operation.result?.steps || []) {
    const data = step.data as
      { groups?: { result?: { group_names?: unknown } } } | undefined;
    const names = data?.groups?.result?.group_names;
    if (names !== undefined) {
      if (
        !Array.isArray(names) ||
        names.some((name) => typeof name !== "string" || !name.trim())
      )
        throw new Error("缓存组列表格式无效，请重新查询缓存组与成员列表。");
      for (const name of names) groups.set(name, groups.get(name) || []);
    }
  }
  for (const member of members) {
    if (!member.groupName) continue;
    const rows = groups.get(member.groupName) || [];
    rows.push(member);
    groups.set(member.groupName, rows);
  }
  return (
    [...groups]
      // Keep genuinely empty groups, but not stale names whose members were deleted.
      .filter(([name, rows]) => rows.length > 0 || !originalGroups.has(name))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, rows]) => {
        const memberRows = rows.map((row) => {
          const matches = managed.filter(
            (item) =>
              item.kind === "cache" &&
              item.name === name &&
              !["deleted", "planned"].includes(item.state) &&
              Array.isArray(item.data.members) &&
              item.data.members.some((member) => member.member_id === row.id),
          );
          const saved = matches.length === 1 ? matches[0] : undefined;
          const record = saved
            ? (saved.data.members as Record<string, unknown>[]).find(
                (m) => m.member_id === row.id,
              )
            : undefined;
          const external = targets[row.id];
          return {
            can_stop: Boolean(saved) || external?.can_stop === true,
            stop_reason: saved
              ? undefined
              : external?.reason || "请刷新列表以匹配成员机器资源",
            member_id: row.id,
            address: row.address,
            weight: row.weight,
            cache_size_mb: row.cacheSizeMb ?? record?.cache_size_mb,
            capacity_source: row.cacheSizeMb != null ? "成员查询" : record?.cache_size_mb != null ? "平台配置" : undefined,
            state: row.stateLabel,
            selectable: row.selectable,
            managed_resource_id: saved?.id,
            machine_id: record?.machine_id || external?.machine_id,
            target_user: record?.target_user || external?.target_user,
            process_stopped:
              record?.process_state === "stopped" || saved?.state === "stopped",
          };
        });
        const saved =
          memberRows.some((row) => row.managed_resource_id) &&
          memberRows.every((row) => row.managed_resource_id)
            ? managed.find(
                (item) =>
                  item.id ===
                  memberRows.find((row) => row.managed_resource_id)
                    ?.managed_resource_id,
              )
            : undefined;
        const activeMembers = memberRows.filter((row) => row.state !== "离线");
        const online = rows.filter((row) => row.stateLabel === "在线").length;
        const state = !rows.length
          ? "cache_empty"
          : rows.every((row) => row.stateLabel === "离线")
            ? "stopped"
            : online === rows.length
              ? "running"
              : online
                ? "partial"
                : "unknown";
        return {
          id: `discovered:${name}`,
          name,
          kind: "cache",
          state,
          created_at: operation.created_at || "",
          data: {
            group_name: name,
            queried_inventory: true,
            online_count: online,
            offline_count: rows.filter((row) => row.stateLabel === "离线")
              .length,
            managed_resource_id: saved?.id,
            can_stop:
              activeMembers.length > 0 &&
              activeMembers.every((row) => row.can_stop),
            stop_reason: activeMembers.length
              ? activeMembers.find((row) => !row.can_stop)?.stop_reason
              : "没有需要停止的成员，成员已离线或组为空",
            members: memberRows,
          },
        };
      })
  );
}
