import { useState } from "react";
import { Run, Scenario, Spec } from "./types";
import { ScenarioParameters } from "./ScenarioParameters";
import { chartGroups } from "./chartGroups";
import { formatBytes } from "./ScenarioParameters";
import { modeLabels } from "./matrix";
import { taskLabels } from "./TaskTable";
export const chartMetrics = {
  create_seconds: {label:"文件创建平均耗时",unit:"s",hint:"越低越好"},
  stat_seconds: {label:"文件 stat平均耗时",unit:"s",hint:"越低越好"},
  remove_seconds: {label:"文件删除平均耗时",unit:"s",hint:"越低越好"},
  file_read_ops_s: {label:"文件读取平均速率",unit:"ops/s",hint:"越高越好"},
  file_read_seconds: {label:"文件读取平均耗时",unit:"s",hint:"越低越好"},
  directory_creation_ops_s: {label:"目录创建平均速率",unit:"ops/s",hint:"越高越好"},
  directory_creation_seconds: {label:"目录创建平均耗时",unit:"s",hint:"越低越好"},
  directory_stat_ops_s: {label:"目录 stat平均速率",unit:"ops/s",hint:"越高越好"},
  directory_stat_seconds: {label:"目录 stat平均耗时",unit:"s",hint:"越低越好"},
  directory_read_ops_s: {label:"目录读取平均速率",unit:"ops/s",hint:"越高越好"},
  directory_read_seconds: {label:"目录读取平均耗时",unit:"s",hint:"越低越好"},
  directory_removal_ops_s: {label:"目录删除平均速率",unit:"ops/s",hint:"越高越好"},
  directory_removal_seconds: {label:"目录删除平均耗时",unit:"s",hint:"越低越好"},
  directory_rename_ops_s: {label:"目录重命名平均速率",unit:"ops/s",hint:"越高越好"},
  directory_rename_seconds: {label:"目录重命名平均耗时",unit:"s",hint:"越低越好"},
  tree_creation_ops_s: {label:"目录树创建平均速率",unit:"ops/s",hint:"越高越好"},
  tree_creation_seconds: {label:"目录树创建平均耗时",unit:"s",hint:"越低越好"},
  tree_removal_ops_s: {label:"目录树删除平均速率",unit:"ops/s",hint:"越高越好"},
  tree_removal_seconds: {label:"目录树删除平均耗时",unit:"s",hint:"越低越好"},

  create_ops_s: {label:"平均创建速率",unit:"ops/s",hint:"越高越好"},
  stat_ops_s: {label:"平均 stat 速率",unit:"ops/s",hint:"越高越好"},
  remove_ops_s: {label:"平均删除速率",unit:"ops/s",hint:"越高越好"},
  bandwidth_mib_s: { label: "平均带宽", unit: "MiB/s", hint: "越高越好" },
  iops: { label: "平均 IOPS", unit: "IO/s", hint: "越高越好" },
  latency_mean_us: { label: "平均延迟", unit: "μs", hint: "越低越好" },
};
export type ChartMetric = keyof typeof chartMetrics;
export function ParameterBarChart({
  run,
  rows,
  label,
  metric,
  valueLabel,
  parameter,
}: {
  run: Run;
  rows: Scenario[];
  label: string;
  parameter: keyof Spec;
  metric: ChartMetric;
  valueLabel: (s: Scenario) => string;
}) {
  const [selected, setSelected] = useState<string>();
  const values = rows.map(
    (s) => run.reports[s.id]?.summary?.statistics?.metrics?.[metric]?.mean,
  );
  const valid = (n: unknown): n is number =>
    typeof n === "number" && Number.isFinite(n) && n >= 0;
  const max = Math.max(0, ...values.filter(valid));
  const scale = max || 1;
  const format = (v: number) =>
    v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  const compact = (v: number) => {
    for (const [divisor, suffix] of [[1e12,"T"],[1e9,"G"],[1e6,"M"],[1e3,"k"]] as const) {
      if (v >= divisor) return Number((v / divisor).toPrecision(3)) + suffix;
    }
    return v > 0 && v < 0.01 ? v.toExponential(0) : String(Number(v.toPrecision(3)));
  };
  const info = chartMetrics[metric];
  const state = (s: Scenario) => {
    const r = run.reports[s.id];
    return (
      r?.state ||
      (r?.summary?.status === "passed"
        ? "success"
        : r?.summary
          ? "failed"
          : ["failed", "cancelled"].includes(run.state)
            ? "skipped"
            : "pending")
    );
  };
  const status = (s: Scenario) =>
    taskLabels[state(s)] ||
    ({ pending: "等待执行", skipped: "未执行" } as Record<string, string>)[
      state(s)
    ] ||
    state(s);
  const groups = chartGroups(rows, parameter);
  const series = Array.from(new Set(rows.map(valueLabel)));
  const colors = [
    "#4477aa",
    "#ee7733",
    "#228833",
    "#cc6677",
    "#aa4499",
    "#66ccee",
    "#998833",
  ];
  const fixedLabel = (fixed: Partial<Spec>) =>
    Object.entries(fixed)
      .filter(([, v]) => v != null)
      .map(([k, v]) => {
        const labels: Record<string, string> = {
          layout: "目录布局",
          rw: "读写",
          direct: "Direct I/O",
          concurrency: "并发",
          iodepth: "深度",
          block_size: "Block",
          file_size: "文件大小",
          file_count: "文件数",
          rounds: "轮次",
          read_percent: "读比例",
        };
        const text =
          k === "layout" ? (v === "shared" ? "共享目录" : "独立目录") : k === "direct"
            ? v
              ? "开启"
              : "关闭"
            : k === "rw"
              ? modeLabels[String(v)] || v
              : ["block_size", "file_size"].includes(k)
                ? formatBytes(String(v))
                : v;
        return `${labels[k] || k} ${text}`;
      })
      .join(" · ");
  const detail = rows.find((s) => s.id === selected);
  const description = (s: Scenario, n: unknown) =>
    `${s.id} · ${label} ${valueLabel(s)} · ${status(s)} · ${info.label} ${valid(n) ? format(n) + " " + info.unit : "无有效数据"}\n` +
    Object.entries(s.parameters)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" · ") +
    (run.reports[s.id]?.error ? "\n" + run.reports[s.id].error : "");
  return (
    <>
      <p className="muted">
        {info.label}（{info.unit}）· {info.hint} · 横轴：{label} ·
        纵轴：性能结果；共 {groups.length} 组，每组固定其他参数，组内比较不同
        {label}
      </p>
      <p className="muted">柱下数值使用简写（k=千、M=百万）；悬停或点击查看精确值。</p>
      <div className="performance-chart-legend">
        {series.map((v, i) => (
          <span key={v}>
            <i style={{ background: colors[i % colors.length] }} />
            {label} {v}
          </span>
        ))}
      </div>
      <div
        className="performance-chart"
        role="group"
        aria-label={label + "柱状图"}
      >
        <div className="performance-chart-axis" aria-hidden="true">
          {[1, 0.75, 0.5, 0.25, 0].map((v) => (
            <span key={v}>{format(scale * v)}</span>
          ))}
        </div>
        <div className="performance-chart-scroll">
          <div className="performance-chart-columns">
            {groups.map((group, groupIndex) => (
              <div className="performance-chart-value-group" key={group.key}>
                <div className="performance-chart-group-bars">
                  {group.scenes.map((s) => {
                    const index = rows.indexOf(s);
                    const n = values[index];
                    return (
                      <button
                        type="button"
                        key={s.id}
                        className={"performance-chart-column " + state(s)}
                        aria-label={description(s, n)}
                        aria-pressed={selected === s.id}
                        title={description(s, n)}
                        onClick={() => setSelected(s.id)}
                      >
                        <span className="performance-chart-track">
                          <span
                            className="performance-chart-bar"
                            style={{
                              height: valid(n) ? `${(n / scale) * 100}%` : "0%",
                              background:
                                colors[
                                  series.indexOf(valueLabel(s)) % colors.length
                                ],
                            }}
                          />
                          {(!valid(n) || n === 0) && (
                            <span className="performance-chart-no-data">
                              {valid(n) ? "0" : "无数据"}
                            </span>
                          )}
                        </span>
                        <span className="performance-chart-number" title={valid(n) ? format(n) + " " + info.unit : "无有效数据"}>{valid(n) ? compact(n) : "—"}</span>
                        <strong>{valueLabel(s)}</strong>
                        <small>
                          #{index + 1} · {status(s)}
                        </small>
                      </button>
                    );
                  })}
                </div>
                <div
                  className="performance-chart-category"
                  title={fixedLabel(group.fixed)}
                >
                  <strong>组合 {groupIndex + 1}</strong>
                  <small>{fixedLabel(group.fixed)}</small>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {detail && (
        <div className="performance-chart-detail">
          <div className="section-title">
            <strong>
              {detail.id} · {status(detail)}
            </strong>
            <button type="button" onClick={() => setSelected(undefined)}>
              收起详情
            </button>
          </div>
          <ScenarioParameters spec={detail.parameters} />
          <p>
            {info.label}：
            {valid(values[rows.indexOf(detail)])
              ? format(values[rows.indexOf(detail)] as number) + " " + info.unit
              : "无有效数据"}
          </p>
          <p>
            有效轮次：
            {run.reports[detail.id]?.summary?.statistics?.successful_rounds ??
              "—"}{" "}
            /{" "}
            {run.reports[detail.id]?.summary?.statistics?.requested_rounds ??
              detail.parameters.rounds}
          </p>
          {(run.reports[detail.id]?.error ||
            run.reports[detail.id]?.summary?.error) && (
            <p className="error">
              {run.reports[detail.id]?.error ||
                run.reports[detail.id]?.summary?.error}
            </p>
          )}
          {!!run.reports[detail.id]?.files?.length && (
            <a href={"#/performance/" + run.id + "/reports/" + detail.id}>
              原始报告
            </a>
          )}
        </div>
      )}
    </>
  );
}
