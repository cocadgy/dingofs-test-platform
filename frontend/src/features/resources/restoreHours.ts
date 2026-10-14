/** UTC hour buckets touched by the trailing time interval. */
export function restoreHourBuckets(hours: number, now = new Date()): string {
  if (!Number.isInteger(hours) || hours < 1 || hours > 168) throw new Error("恢复时间须在 1 至 168 小时之间");
  const end = Math.floor(now.getTime() / 3_600_000);
  const start = Math.floor((now.getTime() - hours * 3_600_000) / 3_600_000);
  return Array.from({ length: end - start + 1 }, (_, index) =>
    new Date((start + index) * 3_600_000).toISOString().slice(0, 13).replace("T", "-"),
  ).join(",");
}
