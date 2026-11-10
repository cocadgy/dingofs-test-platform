import { useState } from "react";
import { Run, Status, elapsed, stateLabels } from "./types";
export function RunList({
  runs,
  onOpen,
}: {
  runs: Run[];
  onOpen: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const rows = runs.filter(
    (r) =>
      (!status || r.state === status) &&
      `${r.name} ${r.snapshot.cluster_name || ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <section className="functional-card">
      <div className="functional-toolbar">
        <input
          type="search"
          aria-label="搜索任务"
          placeholder="搜索任务或集群"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
        <select
          aria-label="任务状态"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(0);
          }}
        >
          <option value="">全部状态</option>
          {Object.entries(stateLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <span>{rows.length} 个任务</span>
      </div>
      <div className="functional-table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务名称</th>
              <th>集群</th>
              <th>状态</th>
              <th>模块进度</th>
              <th>创建时间</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(page * 20, (page + 1) * 20).map((run) => (
              <tr key={run.id}>
                <td>
                  <button
                    className="functional-link"
                    onClick={() => onOpen(run.id)}
                  >
                    {run.name}
                  </button>
                </td>
                <td>{run.snapshot.cluster_name || "—"}</td>
                <td>
                  <Status state={run.state} />
                </td>
                <td>{run.version === 2 && run.children?.length
                  ? `${run.children.filter((child) => ["success", "failed", "cancelled"].includes(child.state)).length} / ${run.children.length} 模块已结束`
                  : "—"}</td>
                <td>{new Date(run.created_at).toLocaleString()}</td>
                <td>{elapsed(run)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && <p className="functional-empty">暂无符合条件的任务。</p>}
      <div className="functional-toolbar functional-pagination">
        <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
          上一页
        </button>
        <span>
          第 {page + 1} / {Math.max(1, Math.ceil(rows.length / 20))} 页
        </span>
        <button
          disabled={(page + 1) * 20 >= rows.length}
          onClick={() => setPage((p) => p + 1)}
        >
          下一页
        </button>
      </div>
    </section>
  );
}
