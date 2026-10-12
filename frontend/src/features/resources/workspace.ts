import type { ResourceSection } from "./types";

export type ResourceArea = ResourceSection | "history";

export const sections: { key: ResourceSection; label: string; hint: string }[] =
  [
    {
      key: "filesystem",
      label: "文件系统",
      hint: "管理文件系统、文件系统配额、目录配额、回收站和目录统计。查询结果保留在操作记录中。",
    },
    {
      key: "cache",
      label: "缓存组",
      hint: "选择已登记且有管理权限的机器创建缓存成员；停止或删除前请核对组名。",
    },
    {
      key: "mount",
      label: "挂载与客户端日志",
      hint: "在指定机器和用户下挂载文件系统，查看挂载状态、卸载和读取有限行数的客户端日志。",
    },
  ];

export function actionGroup(action: string): string {
  if (action.startsWith("quota.fs.")) return "文件系统配额";
  if (action.startsWith("quota.dir.")) return "目录配额";
  if (action.startsWith("trash.")) return "回收站";
  if (action.startsWith("dirstat.")) return "目录统计";
  if (action.startsWith("fs.")) return "基础操作";
  if (action.startsWith("cache.")) return "缓存组操作";
  if (action === "mount.logs") return "客户端日志";
  if (action.startsWith("mount.")) return "挂载操作";
  return "其他操作";
}
