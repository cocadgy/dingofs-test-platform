import { useMemo, useState } from "react";
import { visibleFilesystemName } from "./filesystemOptions";
import type { Parameters, ResourceAction, ResourceOperation } from "./types";
export function filesystemState(value: unknown) {
  return (
    (
      {
        "0": "初始化",
        "1": "正常",
        "2": "已删除",
        "3": "回收中",
        INIT: "初始化",
        NORMAL: "正常",
        DELETED: "已删除",
        RECYCLING: "回收中",
      } as Record<string, string>
    )[String(value).toUpperCase()] || String(value ?? "未知")
  );
}
export function queryTime(operation?: ResourceOperation) {
  return operation?.created_at
    ? new Date(operation.created_at).toLocaleString("zh-CN", { hour12: false })
    : "未查询";
}
function rowsOf(operation?: ResourceOperation): Parameters[] {
  if (operation?.state !== "succeeded") return [];
  for (const step of operation.result?.steps || []) {
    try {
      const data = step.data ?? JSON.parse(step.stdout || "null");
      if (!data || typeof data !== "object") continue;
      const body = data as Parameters;
      const rows = Array.isArray(data)
        ? data
        : ((body.result || body) as Parameters).fs_infos;
      if (Array.isArray(rows))
        return rows.filter(
          (r) =>
            r &&
            typeof r.fs_name === "string" &&
            visibleFilesystemName(r.fs_name),
        );
    } catch {
      /* The shared listing displays parsing errors. */
    }
  }
  return [];
}
const bytes = (value: unknown) => {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "—";
  return n >= 1024 ** 3
    ? `${+(n / 1024 ** 3).toFixed(2)} GiB`
    : n >= 1024 ** 2
      ? `${+(n / 1024 ** 2).toFixed(2)} MiB`
      : `${n} B`;
};
export function FilesystemInventory({
  operation,
  actions,
  disabled,
  onAction,
}: {
  operation?: ResourceOperation;
  actions: ResourceAction[];
  disabled: boolean;
  onAction: (action: ResourceAction, values: Parameters) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<"fs_name" | "fs_id">("fs_name");
  const [ascending, setAscending] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [page, setPage] = useState(0);
  const all = useMemo(() => rowsOf(operation), [operation]);
  const matches = all
    .filter(
      (r) =>
        `${r.fs_name} ${r.fs_id}`.toLowerCase().includes(query.toLowerCase()) &&
        (!status || String(r.status) === status),
    )
    .sort(
      (a, b) =>
        (sort === "fs_id"
          ? Number(a.fs_id) - Number(b.fs_id)
          : String(a.fs_name).localeCompare(String(b.fs_name))) *
        (ascending ? 1 : -1),
    );
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(matches.length / 20) - 1),
  );
  const rows = matches.slice(currentPage * 20, (currentPage + 1) * 20);
  const picked = selected.filter((name) => all.some((r) => r.fs_name === name));
  const shortcuts = [
    ["fs.get", "详情"],
    ["quota.fs.get", "配额"],
    ["quota.dir.get", "目录配额"],
    ["trash.get", "回收站"],
    ["dirstat.info", "目录统计"],
    ["fs.delete", "删除"],
  ];
  function order(key: "fs_name" | "fs_id") {
    if (key === sort) setAscending((v) => !v);
    else {
      setSort(key);
      setAscending(true);
    }
    setPage(0);
  }
  return (
    <section className="resource-filesystem-inventory">
      <div className="resource-inventory-toolbar">
        <label>
          搜索文件系统
          <input
            type="search"
            placeholder="名称或 ID"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label>
          状态
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            <option value="">全部状态</option>
            {[...new Set(all.map((r) => String(r.status)))].map((s) => (
              <option key={s} value={s}>
                {filesystemState(s)}
              </option>
            ))}
          </select>
        </label>
        <span>
          显示 {matches.length} / {all.length} 个
        </span>
      </div>
      {picked.length > 0 && (
        <div className="resource-inventory-actions">
          <strong>已选择 {picked.length} 个文件系统</strong>
          {picked.some((name) => !rows.some((r) => r.fs_name === name)) && (
            <span>
              其中{" "}
              {
                picked.filter((name) => !rows.some((r) => r.fs_name === name))
                  .length
              }{" "}
              项不在当前页中
            </span>
          )}
          <button
            disabled={
              disabled ||
              picked.length > 100 ||
              !actions.some((a) => a.action === "fs.delete_batch")
            }
            onClick={() => {
              const a = actions.find((a) => a.action === "fs.delete_batch");
              if (a) onAction(a, { fs_names: picked });
            }}
          >
            删除所选文件系统
          </button>
          <button onClick={() => setSelected([])}>清空选择</button>
          <small>每批最多 100 个；确认窗口会列出完整目标名单。</small>
        </div>
      )}
      <div className="resource-table-scroll">
        <table
          className="resource-filesystem-table"
          aria-label="文件系统资源列表"
        >
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  aria-label="全选当前页文件系统"
                  disabled={disabled || !rows.length}
                  checked={
                    rows.length > 0 &&
                    rows.every((r) => picked.includes(String(r.fs_name)))
                  }
                  onChange={() => {
                    const names = rows.map((r) => String(r.fs_name));
                    setSelected(
                      rows.every((r) => picked.includes(String(r.fs_name)))
                        ? picked.filter((n) => !names.includes(n))
                        : [...new Set([...picked, ...names])],
                    );
                  }}
                />
              </th>
              <th
                aria-sort={
                  sort === "fs_name"
                    ? ascending
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                <button onClick={() => order("fs_name")}>文件系统名称</button>
              </th>
              <th
                aria-sort={
                  sort === "fs_id"
                    ? ascending
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                <button onClick={() => order("fs_id")}>ID</button>
              </th>
              <th>状态</th>
              <th>容量</th>
              <th>块大小</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r.fs_name)}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`选择文件系统 ${r.fs_name}`}
                    disabled={disabled}
                    checked={picked.includes(String(r.fs_name))}
                    onChange={() =>
                      setSelected(
                        picked.includes(String(r.fs_name))
                          ? picked.filter((n) => n !== r.fs_name)
                          : [...picked, String(r.fs_name)],
                      )
                    }
                  />
                </td>
                <td title={String(r.fs_name)}>{String(r.fs_name)}</td>
                <td>{String(r.fs_id ?? "—")}</td>
                <td>
                  <span className="badge">{filesystemState(r.status)}</span>
                </td>
                <td>{bytes(r.capacity)}</td>
                <td>{bytes(r.block_size)}</td>
                <td>
                  <div className="resource-inventory-actions">
                    {shortcuts
                      .filter(([key]) => actions.some((a) => a.action === key))
                      .map(([key, label]) => (
                        <button
                          key={key}
                          aria-label={`${label} ${r.fs_name}`}
                          disabled={disabled}
                          onClick={() =>
                            onAction(
                              actions.find((a) => a.action === key)!,
                              { fs_name: r.fs_name, fs_id: r.fs_id },
                            )
                          }
                        >
                          {label}
                        </button>
                      ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!matches.length && (
        <p className="muted">
          {operation
            ? all.length
              ? "暂无符合条件的文件系统"
              : "暂无文件系统"
            : "尚未查询文件系统。"}
        </p>
      )}
      {matches.length > 20 && (
        <div className="resource-inventory-actions">
          <button
            disabled={!currentPage}
            onClick={() => setPage(currentPage - 1)}
          >
            上一页
          </button>
          <span>
            第 {currentPage + 1} / {Math.ceil(matches.length / 20)} 页
          </span>
          <button
            disabled={(currentPage + 1) * 20 >= matches.length}
            onClick={() => setPage(currentPage + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  );
}
