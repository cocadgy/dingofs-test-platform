import { useState } from "react";
import { Run, Spec, Tool } from "./types";
import { formatBytes } from "./ScenarioParameters";
import { modeLabels } from "./matrix";
import {
  ParameterBarChart,
  chartMetrics,
  ChartMetric,
} from "./ParameterBarChart";

type Parameter = {
  key: keyof Spec;
  label: string;
  format?: (value: any) => string;
};
const parameters: Parameter[] = [
  { key: "rw", label: "读写模式", format: (v) => modeLabels[v] || v },
  { key: "read_percent", label: "读比例", format: (v) => v + "%" },
  { key: "direct", label: "Direct I/O", format: (v) => (v ? "开启" : "关闭") },
  { key: "concurrency", label: "并发度" },
  { key: "iodepth", label: "I/O 队列深度" },
  { key: "block_size", label: "Block 大小", format: formatBytes },
  { key: "file_size", label: "每文件大小", format: formatBytes },
];
export function ToolComparisonReports({ run }: { run: Run }) {
  const scenes =
    run.snapshot.scenarios ||
    run.snapshot.tests.map((parameters) => ({
      id: parameters.tool,
      tool: parameters.tool,
      parameters,
    }));
  const tools = Array.from(new Set(scenes.map((s) => s.tool)));
  const [chosenMetric, setMetric] = useState<ChartMetric>("bandwidth_mib_s");
  const [chosen, setChosen] = useState<Tool>();
  const tool = chosen && tools.includes(chosen) ? chosen : tools[0];
  const rows = scenes.filter((s) => s.tool === tool);
  const metricKeys: ChartMetric[] = tool==="mdtest" ? ((Object.keys(chartMetrics) as ChartMetric[]).filter(key=>rows.some(row=>run.reports[row.id]?.summary?.statistics?.metrics?.[key]?.mean!=null)).length ? (Object.keys(chartMetrics) as ChartMetric[]).filter(key=>rows.some(row=>run.reports[row.id]?.summary?.statistics?.metrics?.[key]?.mean!=null)) : ["create_ops_s"]) : ["bandwidth_mib_s","iops","latency_mean_us"];
  const metric = metricKeys.includes(chosenMetric) ? chosenMetric : metricKeys[0];
  const fields = (tool==="mdtest" ? [
    {key:"concurrency",label:"MPI 进程数"},
    {key:"mdtest_options",label:"自定义参数组合",format:(v:Record<string,unknown>)=>Object.entries(v).map(([k,x])=>`${k}=${x}`).join(" / ") || "默认"},
    {key:"layout",label:"目录布局",format:(v:string)=>v==="shared"?"共享目录":"独立目录"},
  ] as Parameter[] : parameters).filter(
    (p) =>
      rows.some((s) => s.parameters[p.key] != null) &&
      (p.key !== "read_percent" ||
        rows.some((s) => ["rw", "randrw"].includes(s.parameters.rw))),
  );
  const value = (spec: Spec, p: Parameter) =>
    p.key === "read_percent" && !["rw", "randrw"].includes(spec.rw)
      ? undefined
      : spec[p.key];
  return (
    <div className="performance-comparison-report">
      <div className="performance-report-tools" aria-label="工具报告">
        {tools.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tool === t}
            onClick={() => setChosen(t)}
          >
            {t} 汇总报告
          </button>
        ))}
      </div>
      <h2>{tool} · 参数对比报告</h2>
      <p className="muted">
        共 {rows.length}{" "}
        个场景。每张图包含该工具的全部组合，按当前参数排序。每组固定其他参数，颜色区分当前参数值；缺失指标不计作零。指标为各场景有效轮次均值，不跨场景平均。
      </p>
      <div className="performance-report-tools" aria-label="图表指标">
        {metricKeys.map(key => { const m=chartMetrics[key]; return (
          <button
            key={key}
            type="button"
            aria-pressed={metric === key}
            onClick={() => setMetric(key as ChartMetric)}
          >
            {m.label}（{m.unit}）
          </button>);
        })}
      </div>
      <nav className="performance-report-index" aria-label="参数对比图导航">
        {fields.map((p) => (
          <a
            key={p.key}
            href={"#comparison-" + p.key}
            onClick={(e) => {
              e.preventDefault();
              document
                .getElementById("comparison-" + p.key)
                ?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            {p.label}
          </a>
        ))}
      </nav>
      {fields.map((p) => (
        <section
          key={p.key}
          id={"comparison-" + p.key}
          className="performance-comparison-section"
        >
          <h3>
            不同{p.label}的{chartMetrics[metric].label}对比
          </h3>
          <ParameterBarChart
            key={tool + p.key}
            run={run}
            label={p.label}
            parameter={p.key}
            metric={metric}
            valueLabel={(s) => {
              const v = value(s.parameters, p);
              if (
                p.key === "rw" &&
                ["rw", "randrw"].includes(s.parameters.rw)
              ) {
                return (
                  (modeLabels[s.parameters.rw] || s.parameters.rw) +
                  "（读 " +
                  (s.parameters.read_percent ?? 50) +
                  "%）"
                );
              }
              return v == null ? "不适用" : p.format ? p.format(v) : String(v);
            }}
            rows={[...rows].sort((a, b) => {
              const av = value(a.parameters, p),
                bv = value(b.parameters, p);
              if (av == null) return bv == null ? 0 : 1;
              if (bv == null) return -1;
              return (
                String(av).localeCompare(String(bv), undefined, {
                  numeric: true,
                }) || a.id.localeCompare(b.id)
              );
            })}
          />
        </section>
      ))}
      {!rows.length && <p>暂无场景。</p>}
    </div>
  );
}
