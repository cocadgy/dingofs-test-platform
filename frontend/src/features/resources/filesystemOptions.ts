import type { ResourceOperation } from "./types";

export const visibleFilesystemName = (name: unknown) =>
  typeof name !== "string" || !name.includes("DELETE");

export const selectsFilesystem = (action: string) =>
  action === "mount.create" ||
  action === "fs.get" ||
  action === "fs.delete" ||
  action === "fs.delete_batch" ||
  action.startsWith("quota.") ||
  action.startsWith("trash.") ||
  action.startsWith("dirstat.");

export type FilesystemOption = { name: string; id?: number };

export function filesystemOptions(
  operation: ResourceOperation,
  order: 'name' | 'newest' = 'name',
): FilesystemOption[] {
  for (const step of operation.result?.steps || []) {
    let data = step.data;
    if (data == null && step.stdout) {
      try {
        data = JSON.parse(step.stdout);
      } catch {
        continue;
      }
    }
    if (!data || typeof data !== "object") continue;
    const envelope = data as Record<string, unknown>;
    const body = (envelope.result ?? envelope) as Record<string, unknown>;
    const rows = Array.isArray(data) ? data : body?.fs_infos;
    if (!Array.isArray(rows)) continue;
    if (
      !rows.every(
        (row) =>
          row && typeof row.fs_name === "string" && row.fs_name.length > 0,
      )
    )
      throw new Error("文件系统列表中缺少有效名称，请刷新重试。");
    const options = new Map<string, FilesystemOption>();
    const creationTimes = new Map<string, number>();
    for (const row of rows.filter((row) =>
      visibleFilesystemName(row.fs_name),
    )) {
      const rawId = row.fs_id;
      const id =
        typeof rawId === "number"
          ? rawId
          : typeof rawId === "string" && /^\d+$/.test(rawId)
            ? Number(rawId)
            : NaN;
      const option = {
        name: row.fs_name,
        id: Number.isSafeInteger(id) && id >= 0 ? id : undefined,
      };
      const previous = options.get(option.name);
      if (previous && previous.id !== option.id)
        throw new Error(
          "文件系统列表中存在重名且 ID 不一致的记录，请刷新重试。",
        );
      options.set(option.name, option);
      const rawTime = row.create_time_s;
      const time = typeof rawTime === 'number' || typeof rawTime === 'string'
        ? Number(rawTime) : NaN;
      creationTimes.set(option.name, Number.isFinite(time) && time > 0 ? time : 0);
    }
    return [...options.values()].sort((a, b) =>
      (order === 'newest' ? creationTimes.get(b.name)! - creationTimes.get(a.name)! : 0)
      || a.name.localeCompare(b.name));
  }
  throw new Error("无法识别文件系统列表结果，请查看操作记录并刷新重试。");
}

export function filesystemNames(operation: ResourceOperation): string[] {
  return filesystemOptions(operation).map((option) => option.name);
}
