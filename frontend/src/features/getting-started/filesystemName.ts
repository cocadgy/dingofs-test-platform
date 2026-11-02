export type FilesystemSuffix = "none" | "date" | "seconds" | "milliseconds";

export function formatFilesystemName(base: string, format: FilesystemSuffix, time: Date): string {
  const name = base.trim();
  if (format === "none") return name;
  const pad = (value: number, width = 2) => String(value).padStart(width, "0");
  const day = `${time.getFullYear()}${pad(time.getMonth() + 1)}${pad(time.getDate())}`;
  if (format === "date") return `${name}-${day}`;
  const clock = `${pad(time.getHours())}${pad(time.getMinutes())}${pad(time.getSeconds())}`;
  return `${name}-${day}-${clock}${format === "milliseconds" ? `-${pad(time.getMilliseconds(), 3)}` : ""}`;
}
