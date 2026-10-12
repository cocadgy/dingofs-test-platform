import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import {
  type ClusterRow,
  type Operation,
  dateText,
  statusNames,
} from "./types";
const columns = [
  ["name", "别名"],
  ["external_name", "集群名称"],
  ["cluster_kind", "集群类型"],
  ["machine_name", "dingo 执行机器"],
  ["os_user", "执行用户"],
  ["state", "运行状态"],
  ["node_count", "节点数"],
  ["service_count", "服务数"],
  ["running_instances", "运行实例／预期实例"],
  ["status_success_at", "最近成功采集时间"],
  ["status_attempt_state", "最近采集结果"],
] as const;
type Key = (typeof columns)[number][0];
export type TableState = {
  filters: Partial<Record<Key, string>>;
  sortBy: Key;
  desc: boolean;
  page: number;
};
export const initialState: TableState = {
  filters: {},
  sortBy: "name",
  desc: false,
  page: 0,
};
function cell(row: ClusterRow, k: Key): string {
  const v = row[k];
  if (v == null) return "";
  if (k === "machine_name") return `${v} · ${row.machine_address}`;
  if (k === "state" || k === "status_attempt_state")
    return statusNames[String(v)] || String(v);
  if (k === "status_success_at") return dateText(v as string);
  if (k === "running_instances") return `${v}/${row.expected_instances ?? ""}`;
  return String(v);
}
export function ClusterOverview({
  admin = false,
  userId,
  state,
  onStateChange,
  onOpen,
}: {
  admin?: boolean;
  userId?: string;
  state: TableState;
  onStateChange: (s: TableState) => void;
  onOpen: (id: string) => void;
}) {
  const [items, setItems] = useState<ClusterRow[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [refreshing, setRefreshing] = useState(false),
    [progress, setProgress] = useState("");
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    (async () => {
      let offset = 0;
      const all: ClusterRow[] = [];
      while (true) {
        const r = await api<{ items: ClusterRow[]; total: number }>(
          `/clusters/overview?limit=200&offset=${offset}`,
        );
        if (!active) return;
        all.push(...r.items);
        offset += r.items.length;
        if (!r.items.length || offset >= r.total) break;
      }
      if (active) setItems(all);
    })()
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);
  const filtered = useMemo(
    () =>
      items
        .filter((r) =>
          columns.every(([k]) =>
            cell(r, k)
              .toLowerCase()
              .includes((state.filters[k] || "").trim().toLowerCase()),
          ),
        )
        .sort((a, b) => {
          const x = a[state.sortBy],
            y = b[state.sortBy];
          if (x == null || y == null)
            return x == null ? (y == null ? 0 : 1) : -1;
          const cmp =
            typeof x === "number" && typeof y === "number"
              ? x - y
              : state.sortBy === "status_success_at"
                ? new Date(x as string).getTime() -
                  new Date(y as string).getTime()
                : String(x).localeCompare(String(y), "zh-CN", {
                    numeric: true,
                  });
          return cmp * (state.desc ? -1 : 1) || a.id.localeCompare(b.id);
        }),
    [items, state],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 20)),
    page = Math.min(state.page, pages - 1);
  async function refreshStatuses() {
    setRefreshing(true);
    setError("");
    let failures = 0,
      done = 0;
    try {
      for (const row of filtered) {
        if (!live.current) break;
        if (
          row.archived ||
          row.binding_state !== "verified" ||
          !(admin || (!!userId && row.creator_id === userId))
        )
          continue;
        try {
          let op = await api<Operation>(
            `/clusters/${row.id}/refresh-status`,
            "POST",
            { base_revision: row.revision },
          );
          while (live.current && ["pending", "running"].includes(op.state)) {
            await new Promise((r) => setTimeout(r, 1200));
            if (!live.current) break;
            op = await api<Operation>("/cluster-operations/" + op.id);
          }
          if (op.state !== "succeeded") failures++;
        } catch {
          failures++;
        }
        done++;
        if (live.current)
          setProgress(
            `已处理 ${done} 个集群，${failures} 个需进入详情查看或认证`,
          );
      }
    } finally {
      if (live.current) {
        setRefreshing(false);
        setReload((n) => n + 1);
      }
    }
  }
  return (
    <section className="panel machine-overview" aria-label="集群概览">
      <div className="machine-table-toolbar">
        <strong>
          共 {items.length} 个 · 筛选结果 {filtered.length} 个
        </strong>
        <div className="actions">
          <button
            onClick={() => onStateChange({ ...state, filters: {}, page: 0 })}
          >
            清空搜索
          </button>
          <button
            disabled={loading || refreshing}
            onClick={() => setReload((n) => n + 1)}
          >
            刷新列表
          </button>
          <button
            disabled={
              loading ||
              refreshing ||
              !filtered.some(
                (r) =>
                  !r.archived &&
                  r.binding_state === "verified" &&
                  (admin || (!!userId && r.creator_id === userId)),
              )
            }
            onClick={refreshStatuses}
          >
            刷新筛选结果状态
          </button>
        </div>
      </div>
      {progress && <p role="status">{progress}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="machine-table-scroll" tabIndex={0}>
        <table className="machine-table" aria-label="集群列表">
          <thead>
            <tr>
              {columns.map(([k, label]) => (
                <th
                  key={k}
                  aria-sort={
                    state.sortBy === k
                      ? state.desc
                        ? "descending"
                        : "ascending"
                      : "none"
                  }
                >
                  <button
                    className="sort-heading"
                    aria-label={`按${label}排序`}
                    onClick={() =>
                      onStateChange({
                        ...state,
                        sortBy: k,
                        desc: state.sortBy === k ? !state.desc : false,
                        page: 0,
                      })
                    }
                  >
                    {label}{" "}
                    {state.sortBy === k ? (state.desc ? "↓" : "↑") : "↕"}
                  </button>
                  <input
                    type="search"
                    aria-label={`搜索${label}`}
                    placeholder="搜索…"
                    value={state.filters[k] || ""}
                    onChange={(e) =>
                      onStateChange({
                        ...state,
                        filters: { ...state.filters, [k]: e.target.value },
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
              filtered.slice(page * 20, (page + 1) * 20).map((row) => (
                <tr key={row.id} onClick={() => onOpen(row.id)}>
                  {columns.map(([k]) => (
                    <td key={k} title={cell(row, k)}>
                      {k === "name" ? (
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
                          {row.archived && <small>已归档</small>}
                          {row.binding_state !== "verified" && (
                            <small>需要确认管理入口</small>
                          )}
                        </>
                      ) : (
                        <span
                          className={
                            "machine-cell " +
                            (k === "state" && row.state === "degraded"
                              ? "error"
                              : "")
                          }
                        >
                          {cell(row, k)}
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {loading ? (
        <p>正在读取集群列表…</p>
      ) : (
        !error &&
        !filtered.length && (
          <p className="empty">暂无匹配集群，可点击“发现集群”导入。</p>
        )
      )}
      <div className="pagination">
        <span>点击行查看详情 · 运行状态不等同业务健康</span>
        <div className="actions">
          <button
            disabled={!page || loading}
            onClick={() => onStateChange({ ...state, page: page - 1 })}
          >
            上一页
          </button>
          <span>
            第 {page + 1} / {pages} 页
          </span>
          <button
            disabled={page + 1 >= pages || loading}
            onClick={() => onStateChange({ ...state, page: page + 1 })}
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}
