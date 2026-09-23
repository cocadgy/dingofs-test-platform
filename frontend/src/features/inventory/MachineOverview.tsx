import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { bytes, statusNames } from "./MachineHardware";
export type OverviewRow = components["schemas"]["MachineOverviewItem"];
type ColumnKey =
  | "name"
  | "ip"
  | "cpu_model"
  | "physical_cores"
  | "logical_cores"
  | "memory_bytes"
  | "disk_bytes"
  | "max_speed_mbps"
  | "rdma_devices"
  | "info_updated_at";
export type TableState = {
  filters: Partial<Record<ColumnKey, string>>;
  sortBy: ColumnKey;
  sortDir: "asc" | "desc";
  page: number;
};
export const initialTableState: TableState = {
  filters: {},
  sortBy: "name",
  sortDir: "asc",
  page: 0,
};
export const columns: { key: ColumnKey; label: string }[] = [
  { key: "name", label: "资源名" },
  { key: "ip", label: "IP" },
  { key: "cpu_model", label: "CPU型号" },
  { key: "physical_cores", label: "物理CPU核数" },
  { key: "logical_cores", label: "逻辑CPU核数" },
  { key: "memory_bytes", label: "总内存" },
  { key: "disk_bytes", label: "总磁盘" },
  { key: "max_speed_mbps", label: "网卡速率（最大）" },
  { key: "rdma_devices", label: "RDMA设备" },
  { key: "info_updated_at", label: "信息更新时间" },
];
function dateText(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "未知";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
export function formatCell(row: OverviewRow, key: ColumnKey): string {
  const value = row[key];
  if (value == null) return "";
  if (key === "memory_bytes" || key === "disk_bytes")
    return bytes(value as number);
  if (key === "max_speed_mbps") return `${value} Mbps`;
  if (key === "rdma_devices") return (value as string[]).join(", ") || "无";
  if (key === "info_updated_at") return dateText(value as string);
  return String(value);
}
const collator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});
export function filterAndSort(rows: OverviewRow[], state: TableState) {
  const filtered = rows.filter((row) =>
    columns.every((c) =>
      formatCell(row, c.key)
        .toLocaleLowerCase()
        .includes((state.filters[c.key] || "").trim().toLocaleLowerCase()),
    ),
  );
  return filtered.sort((a, b) => {
    let left: string | number | null = a[state.sortBy] as
      string | number | null;
    let right: string | number | null = b[state.sortBy] as
      string | number | null;
    if (left == null || right == null) {
      if (left == null && right != null) return 1;
      if (right == null && left != null) return -1;
    }
    if (state.sortBy === "info_updated_at") {
      left = left == null ? null : new Date(left).getTime();
      right = right == null ? null : new Date(right).getTime();
    }
    if (state.sortBy === "rdma_devices") {
      left = a.rdma_devices?.join(", ") ?? null;
      right = b.rdma_devices?.join(", ") ?? null;
    }
    const cmp =
      left == null || right == null
        ? 0
        : typeof left === "number" && typeof right === "number"
          ? left - right
          : collator.compare(String(left), String(right));
    return (
      cmp * (state.sortDir === "asc" ? 1 : -1) ||
      collator.compare(a.name, b.name) ||
      a.id.localeCompare(b.id)
    );
  });
}
export function MachineOverview({
  state,
  onStateChange,
  onOpen,
}: {
  state: TableState;
  onStateChange: (state: TableState) => void;
  onOpen: (id: string) => void;
}) {
  const [items, setItems] = useState<OverviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    (async () => {
      const all: OverviewRow[] = [];
      let offset = 0;
      while (live) {
        const response = await api<
          components["schemas"]["MachineOverviewList"]
        >(`/machines/overview?limit=200&offset=${offset}`);
        if (!live) return;
        all.push(...response.items);
        offset += response.items.length;
        if (!response.items.length || offset >= response.total) break;
      }
      if (live)
        setItems([...new Map(all.map((row) => [row.id, row])).values()]);
    })()
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [reload]);
  const filtered = useMemo(() => filterAndSort(items, state), [items, state]);
  const page = Math.min(
    state.page,
    Math.max(0, Math.ceil(filtered.length / 20) - 1),
  );
  const visible = filtered.slice(page * 20, (page + 1) * 20);
  return (
    <section className="panel machine-overview" aria-label="机器资源概览">
      <div className="machine-table-toolbar">
        <div>
          <strong>机器资源概览</strong>
          <span className="muted">
            {loading
              ? "正在加载全部机器…"
              : `共 ${items.length} 台 · 筛选结果 ${filtered.length} 台`}
          </span>
        </div>
        <div className="actions">
          <button
            onClick={() => onStateChange({ ...state, filters: {}, page: 0 })}
          >
            清空搜索
          </button>
          <button disabled={loading} onClick={() => setReload((n) => n + 1)}>
            刷新概览
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}，请点击“刷新概览”重试。
        </p>
      )}
      <div
        className="machine-table-scroll"
        tabIndex={0}
        aria-label="机器表格，可横向滚动"
      >
        <table
          className="machine-table"
          aria-label="机器资源列表"
          aria-busy={loading}
        >
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={
                    state.sortBy === c.key
                      ? state.sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    className="sort-heading"
                    aria-label={`按${c.label}排序`}
                    onClick={() =>
                      onStateChange({
                        ...state,
                        sortBy: c.key,
                        sortDir:
                          state.sortBy === c.key && state.sortDir === "asc"
                            ? "desc"
                            : "asc",
                        page: 0,
                      })
                    }
                  >
                    {c.label}
                    <span aria-hidden="true">
                      {state.sortBy === c.key
                        ? state.sortDir === "asc"
                          ? "↑"
                          : "↓"
                        : "↕"}
                    </span>
                  </button>
                  <input
                    type="search"
                    aria-label={`搜索${c.label}`}
                    placeholder="搜索…"
                    maxLength={120}
                    value={state.filters[c.key] || ""}
                    onChange={(e) =>
                      onStateChange({
                        ...state,
                        filters: { ...state.filters, [c.key]: e.target.value },
                        page: 0,
                      })
                    }
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!loading &&
              !error &&
              visible.map((row) => (
                <tr key={row.id} onClick={() => onOpen(row.id)}>
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      title={
                        c.key === "ip"
                          ? `登记地址：${row.address}\n${formatCell(row, c.key)}`
                          : formatCell(row, c.key)
                      }
                    >
                      {c.key === "name" ? (
                        <>
                          <button
                            className="machine-name"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpen(row.id);
                            }}
                          >
                            {row.name}
                          </button>
                          <small>
                            {row.archived
                              ? "已归档"
                              : statusNames[row.collection_status] || "未知"}
                            {row.hardware_source === "partial"
                              ? " · 部分数据"
                              : ""}
                          </small>
                        </>
                      ) : (
                        <span className="machine-cell">
                          {formatCell(row, c.key)}
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
        {loading ? (
          <p className="empty" role="status">
            正在加载全部机器信息…
          </p>
        ) : (
          !error &&
          !filtered.length && (
            <p className="empty">
              {items.length
                ? "没有匹配的机器，请调整搜索条件。"
                : "暂无机器资源，请先登记机器。"}
            </p>
          )
        )}
      </div>
      <div className="pagination">
        <span>点击机器行查看详情 · 容量按物理磁盘累计 · 未知值排序置后</span>
        <div className="actions">
          <button
            disabled={loading || !!error || page === 0}
            onClick={() => onStateChange({ ...state, page: page - 1 })}
          >
            上一页
          </button>
          <span>
            第 {page + 1} / {Math.max(1, Math.ceil(filtered.length / 20))} 页
          </span>
          <button
            disabled={loading || !!error || (page + 1) * 20 >= filtered.length}
            onClick={() => onStateChange({ ...state, page: page + 1 })}
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}
