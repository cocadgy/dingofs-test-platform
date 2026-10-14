import { useState } from "react";
import { chartMetrics, ChartMetric } from "./ParameterBarChart";
import { Run } from "./types";
const reportUrl = (id: string, tool: string, file: string) =>
  `/api/v1/performance/runs/${encodeURIComponent(id)}/reports/${encodeURIComponent(tool)}/${encodeURIComponent(file)}`;
export function ReportCards({ run }: { run: Run }) {
  const [reportTool, setReportTool] = useState("");
  return (
    <>
      {" "}
      {Object.entries(run.reports).map(([tool, r]) => (
        <section className="performance-report" key={tool}>
          <h3>
            {tool} · {r.summary?.status === "passed" ? "通过" : "未完成 / 失败"}
          </h3>
          <p>
            有效轮次：{r.summary?.statistics?.successful_rounds ?? 0} /{" "}
            {r.summary?.statistics?.requested_rounds ?? "—"}
          </p>
          <div className="performance-metrics">
            {(r.tool === "mdtest" || run.snapshot.scenarios?.find(s=>s.id===tool)?.tool === "mdtest" || tool === "mdtest" ? Object.keys(r.summary?.statistics?.metrics || {}).map(key=>[key,chartMetrics[key as ChartMetric]?.label || key,chartMetrics[key as ChartMetric]?.unit || ""]) : [
              ["bandwidth_mib_s", "平均带宽", "MiB/s"],
              ["iops", "平均 IOPS", "IO/s"],
              ["latency_mean_us", "平均延迟", "μs"],
            ]).map(([key, label, unit]) => (
              <div key={key}>
                <small>{label}</small>
                <strong>
                  {r.summary?.statistics?.metrics?.[key]?.mean?.toFixed(2) ??
                    "—"}{" "}
                  <small>{unit}</small>
                </strong>
              </div>
            ))}
          </div>
          <div className="actions">
            {r.files.includes("index.html") && (
              <>
                <button
                  onClick={() => setReportTool(reportTool === tool ? "" : tool)}
                >
                  查看网页报告
                </button>
                <a
                  href={reportUrl(run.id, tool, "index.html")}
                  target="_blank"
                  rel="noreferrer"
                >
                  新标签页打开
                </a>
              </>
            )}
            {r.files.includes("summary.json") && (
              <a
                href={reportUrl(run.id, tool, "summary.json")}
                target="_blank"
                rel="noreferrer"
              >
                JSON 报告
              </a>
            )}
          </div>
          <details>
            <summary>报告附件与远端目录</summary>
            <p>{r.remote_path}</p>
            <p>大于4MiB的单个附件或累计超过16MiB的附件保留在远端目录。</p>
            {r.files.map((file) => (
              <div key={file}>
                <a
                  href={reportUrl(run.id, tool, file)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {file}
                </a>
              </div>
            ))}
          </details>
          {reportTool === tool && (
            <iframe
              title={tool + " 性能报告"}
              sandbox="allow-scripts"
              src={reportUrl(run.id, tool, "index.html")}
            />
          )}
        </section>
      ))}
    </>
  );
}
