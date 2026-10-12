import { useMemo, useState } from "react";
import { sizeText, type RemoteFile } from "./types";

type SortKey = "name" | "mtime" | "type" | "size";
type Direction = "ascending" | "descending";
const columns: { key: SortKey; label: string }[] = [
  { key: "name", label: "名称" },
  { key: "mtime", label: "修改时间" },
  { key: "type", label: "类型" },
  { key: "size", label: "大小" },
];
const collator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});
const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function modifiedTime(value: RemoteFile["mtime"]): number | null {
  const time =
    typeof value === "number"
      ? value * 1000
      : typeof value === "string" && value.trim()
        ? Date.parse(value)
        : NaN;
  return Number.isFinite(time) && Number.isFinite(new Date(time).getTime())
    ? time
    : null;
}
function fileType(name: string): string {
  if (/\.(?:INFO|WARNING|ERROR|FATAL)(?:\.\d{8}-\d{6}(?:\.\d+)?)?$/i.test(name))
    return "日志文件";
  const stem = name.replace(/(?:\.\d+)+$/, "");
  const dot = stem.lastIndexOf(".");
  if (dot <= 0 || dot === stem.length - 1) return "文件";
  const extension = stem.slice(dot + 1).toLowerCase();
  if (extension === "log") return "日志文件";
  if (extension === "txt") return "文本文档";
  if (extension === "json") return "JSON 文件";
  if (extension === "yaml" || extension === "yml") return "YAML 文件";
  if (extension === "conf" || extension === "cfg") return "配置文件";
  if (["gz", "zip", "bz2", "xz", "zst", "tgz"].includes(extension))
    return `${extension.toUpperCase()} 压缩文件`;
  return `${extension.toUpperCase()} 文件`;
}

export function LogFileTable({
  files,
  disabled = false,
  onOpen,
}: {
  files: RemoteFile[];
  disabled?: boolean;
  onOpen: (file: RemoteFile) => void;
}) {
  const [selected, setSelected] = useState<string>();
  const [sort, setSort] = useState<{ key: SortKey; direction: Direction }>({
    key: "mtime",
    direction: "descending",
  });
  const rows = useMemo(
    () =>
      files.map((file, index) => {
        const name =
          typeof file.name === "string" && file.name.trim() ? file.name : null;
        const mtime = modifiedTime(file.mtime);
        const size =
          typeof file.size === "number" &&
          Number.isFinite(file.size) &&
          file.size >= 0
            ? file.size
            : null;
        return {
          file,
          index,
          name,
          mtime,
          size,
          type: name ? fileType(name) : null,
          date: mtime == null ? "—" : dateFormat.format(mtime),
        };
      }),
    [files],
  );
  const ordered = useMemo(
    () =>
      [...rows].sort((a, b) => {
        const left = a[sort.key],
          right = b[sort.key];
        if (left == null || right == null)
          return left == null && right == null
            ? a.index - b.index
            : left == null
              ? 1
              : -1;
        const comparison =
          typeof left === "number" && typeof right === "number"
            ? left - right
            : collator.compare(String(left), String(right));
        return comparison
          ? comparison * (sort.direction === "ascending" ? 1 : -1)
          : a.index - b.index;
      }),
    [rows, sort],
  );
  return (
    <div className="log-file-table-scroll">
      <table
        className="log-file-table"
        aria-label="日志文件列表"
        aria-disabled={disabled || undefined}
      >
        <thead>
          <tr>
            {columns.map(({ key, label }) => (
              <th
                key={key}
                scope="col"
                aria-sort={sort.key === key ? sort.direction : "none"}
              >
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    setSort((previous) => ({
                      key,
                      direction:
                        previous.key === key &&
                        previous.direction === "ascending"
                          ? "descending"
                          : "ascending",
                    }))
                  }
                >
                  {label}
                  {sort.key === key && (
                    <span aria-hidden="true">
                      {sort.direction === "ascending" ? "↑" : "↓"}
                    </span>
                  )}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordered.map(({ file, name, mtime, size, type, date }) => (
            <tr
              key={file.file_id}
              className={selected === file.file_id ? "selected" : undefined}
              aria-selected={selected === file.file_id}
              aria-disabled={disabled || undefined}
              tabIndex={disabled ? -1 : 0}
              onFocus={() => {
                if (!disabled) setSelected(file.file_id);
              }}
              onClick={() => {
                if (!disabled) setSelected(file.file_id);
              }}
              onDoubleClick={() => {
                if (!disabled) {
                  setSelected(file.file_id);
                  onOpen(file);
                }
              }}
              onKeyDown={(event) => {
                if (!disabled && event.key === "Enter" && !event.repeat) {
                  event.preventDefault();
                  setSelected(file.file_id);
                  onOpen(file);
                }
              }}
            >
              <td className="log-file-name">{name || "—"}</td>
              <td>
                {mtime == null ? (
                  "—"
                ) : (
                  <time dateTime={new Date(mtime).toISOString()}>{date}</time>
                )}
              </td>
              <td>{type || "—"}</td>
              <td className="log-file-size">
                {size == null ? "—" : sizeText(size)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
