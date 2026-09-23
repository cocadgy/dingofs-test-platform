import type { components } from "../../api/schema";
export type Operation = components["schemas"]["OperationView"];
export type ClusterRow = components["schemas"]["ClusterSummary"];
export type ClusterDetailData = components["schemas"]["ClusterDetailView"];
export type ImportResult = components["schemas"]["ImportResult"];
export const statusNames: Record<string, string> = {
  running: "全部运行",
  degraded: "部分异常",
  stopped: "全部停止",
  unknown: "未知",
  never: "未采集",
  pending: "等待采集",
  succeeded: "成功",
  failed: "失败",
  needs_password: "等待密码",
  needs_trust: "等待信任确认",
  interrupted: "已中断",
  cancelled: "已取消",
};
export function dateText(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "";
}
