import { useState } from "react";
import { Run } from "./types";
import { ScenarioParameters } from "./ScenarioParameters";
const labels: Record<string, string> = {
  pending: "等待执行",
  running: "运行中",
  success: "通过",
  failed: "失败",
  skipped: "未执行",
  cancelled: "已取消",
  unknown: "待确认",
};
export function ScenarioResults({ run }: { run: Run }) {
  const [filter, setFilter] = useState("all");
  const scenes =
    run.snapshot.scenarios ||
    run.snapshot.tests.map((parameters) => ({
      id: parameters.tool,
      tool: parameters.tool,
      parameters,
    }));
  const columns = [
    ...(scenes.some(s=>s.tool!=="mdtest") ? [["bandwidth_mib_s","平均带宽 MiB/s"],["iops","平均 IOPS"],["latency_mean_us","平均延迟 μs"]] : []),
    ...(scenes.some(s=>s.tool==="mdtest") ? [["create_ops_s","创建 ops/s"],["stat_ops_s","stat ops/s"],["remove_ops_s","删除 ops/s"]] : []),
  ];
  const state = (id: string) => {
    const report = run.reports[id];
    return (
      report?.state ||
      (report?.summary?.status === "passed"
        ? "success"
        : report?.summary
          ? "failed"
          : ["failed", "cancelled"].includes(run.state)
            ? "skipped"
            : "pending")
    );
  };
  const count = (value: string) =>
    scenes.filter((s) => state(s.id) === value).length;
  return (
    <div>
      <p>
        共 {scenes.length} 个场景 · 通过 {count("success")} · 失败{" "}
        {count("failed")} · 未执行 {count("skipped")} · 运行中{" "}
        {count("running")}
      </p>
      <label>
        场景状态{" "}
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">全部</option>
          {Object.entries(labels).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <div className="table-scroll performance-scene-scroll">
        <table className="performance-data-table">
          <thead>
            <tr>
              <th>场景</th>
              <th>参数组合</th>
              <th>状态</th>
              {columns.map(([key,label])=><th key={key}>{label}</th>)}
              <th>报告</th>
            </tr>
          </thead>
          <tbody>
            {scenes
              .filter((s) => filter === "all" || state(s.id) === filter)
              .map((s) => {
                const result = run.reports[s.id];
                const metrics = result?.summary?.statistics?.metrics;
                return (
                  <tr key={s.id}>
                    <td>{s.id}</td>
                    <td>
                      <ScenarioParameters spec={s.parameters} />
                    </td>
                    <td>
                      <span className={"performance-state " + state(s.id)}>
                        {labels[state(s.id)] || state(s.id)}
                      </span>
                      {result?.error && <p className="error">{result.error}</p>}
                    </td>
                    {columns.map(([k]) => (
                      <td key={k}>{metrics?.[k]?.mean?.toFixed(2) ?? "—"}</td>
                    ))}
                    <td>
                      <button
                        disabled={!result?.files?.length}
                        onClick={() => {
                          window.location.hash =
                            "#/performance/" + run.id + "/reports/" + s.id;
                        }}
                      >
                        查看报告
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
