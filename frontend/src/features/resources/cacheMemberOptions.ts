import type { ResourceOperation } from "./types";

export type CacheMemberOption = {
  id: string;
  groupName: string;
  address: string;
  stateLabel: string;
  selectable: boolean;
  weight?: number;
  cacheSizeMb?: number;
};

function object(value: unknown): Record<string, unknown> | undefined {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function checkResponse(value: Record<string, unknown>) {
  const error = object(value.error);
  if (
    [error?.code, error?.errcode].some(
      (code) =>
        code != null &&
        code !== 0 &&
        code !== "0" &&
        code !== "OK" &&
        code !== "kOk" &&
        code !== false,
    )
  )
    throw new Error("缓存成员列表查询失败，请查看操作记录并刷新重试。");
}

function memberState(state: unknown) {
  if (state === 0 || state === "0" || state === "CacheGroupMemberStateUnknown")
    return { stateLabel: "未知", selectable: true };
  if (state === 3 || state === "3" || state === "CacheGroupMemberStateOffline")
    return { stateLabel: "离线", selectable: true };
  if (
    state === 1 ||
    state === "1" ||
    state === "CacheGroupMemberStateOnline" ||
    state === "CacheGroupMemberStateNormal"
  )
    return { stateLabel: "在线", selectable: false };
  return {
    stateLabel:
      typeof state === "string" || typeof state === "number"
        ? `未识别状态（${state}）`
        : "未返回有效状态",
    selectable: false,
  };
}

function memberAddress(row: Record<string, unknown>): string {
  const ip = typeof row.ip === "string" ? row.ip : "";
  const port =
    typeof row.port === "string" || typeof row.port === "number"
      ? String(row.port)
      : "";
  if (!ip) return "未返回地址";
  if (!port) return ip;
  return `${ip.includes(":") && !ip.startsWith("[") ? `[${ip}]` : ip}:${port}`;
}

export function cacheMemberOptions(
  operation: ResourceOperation,
): CacheMemberOption[] {
  const options = new Map<string, CacheMemberOption>();
  let found = false;
  for (const step of operation.result?.steps || []) {
    let data = step.data;
    if (data == null && step.stdout) {
      try {
        data = JSON.parse(step.stdout);
      } catch {
        continue;
      }
    }
    let body = object(data);
    if (!body) continue;
    checkResponse(body);
    // cache.list combines the separate group and member CLI responses.
    const members = object(body.members);
    if (members) {
      body = members;
      checkResponse(body);
    }
    const result = object(body.result);
    if (result) {
      body = result;
      checkResponse(body);
    }
    if (!("members" in body)) {
      // An identified successful member response may omit an empty repeated field.
      if (members && result) found = true;
      continue;
    }
    if (!Array.isArray(body.members))
      throw new Error("缓存成员列表格式无效，请查看操作记录并刷新重试。");
    found = true;
    for (const value of body.members) {
      const row = object(value);
      const id = row?.member_id;
      if (typeof id !== "string" || !id.trim())
        throw new Error("缓存成员列表中缺少有效成员 ID，请刷新重试。");
      if (options.has(id))
        throw new Error("缓存成员列表中存在重复 ID 或冲突记录，请刷新重试。");
      options.set(id, {
        id,
        groupName: typeof row!.group_name === "string" ? row!.group_name : "",
        address: memberAddress(row!),
        weight: typeof row!.weight === "number" ? row!.weight : undefined,
        cacheSizeMb: typeof row!.cache_size_mb === "number" ? row!.cache_size_mb : undefined,
        ...memberState(row!.state),
      });
    }
  }
  if (!found)
    throw new Error("无法识别缓存成员列表结果，请查看操作记录并刷新重试。");
  return [...options.values()];
}
