import { useState } from "react";
import { Run } from "./types";
export const taskLabels: Record<string, string> = {
  queued: "等待执行",
  running: "运行中",
  cancelling: "正在取消",
  success: "通过",
  failed: "失败",
  cancelled: "已取消",
  unknown: "状态待确认",
};
export const taskActive = (state: string) =>
  ["queued", "running", "cancelling", "unknown"].includes(state);
export function TaskTable({
  runs,
  selected,
  busy,
  onRerun,
}: {
  runs: Run[];
  selected: string;
  busy: boolean;
  onRerun: (run: Run) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const rows = runs.filter(
    (r) =>
      (!status || r.state === status) &&
      [r.name, r.snapshot.machine_name, r.snapshot.target_path]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className="panel performance-task-panel">
      <div className="section-title">
        <div>
          <h2>测试任务与报告</h2>
          <p className="muted">
            {runs.length} 个任务 · 每次重跑创建独立任务和报告
          </p>
        </div>
        <div className="performance-table-filters">
          <input
            aria-label="搜索测试任务"
            placeholder="搜索任务、机器或目录"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            aria-label="任务状态"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">全部状态</option>
            {Object.entries(taskLabels).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="table-scroll">
        <table className="performance-data-table">
          <thead>
            <tr>
              <th>任务名称</th>
              <th>执行目标</th>
              <th>工具 / 场景</th>
              <th>状态</th>
              <th>进度</th>
              <th>耗时</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const seconds = Math.max(
                0,
                Math.round(
                  (new Date(r.finished_at || Date.now()).getTime() -
                    new Date(r.created_at).getTime()) /
                    1000,
                ),
              );
              return (
                <tr key={r.id} className={selected === r.id ? "selected" : ""}>
                  <td className="performance-task-name">
                    <a href={"#/performance/" + r.id}>{r.name}</a>
                  </td>
                  <td>
                    <strong>{r.snapshot.machine_name}</strong>
                    <small
                      className="performance-target-path"
                      title={r.snapshot.target_path}
                    >
                      {r.snapshot.target_path}
                    </small>
                  </td>
                  <td>
                    {Array.from(
                      new Set(r.snapshot.tests.map((t) => t.tool)),
                    ).join(" / ")}
                    <small className="muted">
                      {r.snapshot.tests.length} 个场景
                    </small>
                  </td>
                  <td>
                    <span className={"performance-state " + r.state}>
                      {taskLabels[r.state] || r.state}
                    </span>
                  </td>
                  <td>
                    <div className="performance-table-progress">
                      <progress max={100} value={r.progress} />
                      <span>{r.progress}%</span>
                    </div>
                  </td>
                  <td>
                    {seconds >= 60
                      ? `${Math.floor(seconds / 60)}分${seconds % 60}秒`
                      : `${seconds}秒`}
                  </td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <div className="performance-row-actions">
                      <a href={"#/performance/" + r.id + "/reports"}>
                        查看报告
                      </a>
                      {r.can_manage && (
                        <button
                          type="button"
                          disabled={busy || taskActive(r.state)}
                          title={
                            taskActive(r.state)
                              ? "任务结束后可重跑"
                              : "使用原参数创建新任务"
                          }
                          onClick={() => onRerun(r)}
                        >
                          重跑
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && (
          <p className="performance-empty">
            {runs.length
              ? "没有匹配的任务"
              : "暂无性能任务，点击“新建测试”开始。"}
          </p>
        )}
      </div>
    </div>
  );
}
