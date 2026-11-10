import { useState } from "react";
import { ModuleRunView, Status, moduleLabels, verifiedCaseCounts } from "./types";

const caseLabels: Record<string, string> = {
  PASS: "通过", FAIL: "失败", SKIP: "跳过", KNOWN_BUG: "已知问题",
};
const reportLabels: Record<string, string> = {
  pending: "报告生成中", missing: "报告未生成", failed: "报告生成失败",
};
const safeReportPath = (path: unknown): path is string =>
  typeof path === "string" && path.endsWith("/index.html") &&
  !path.startsWith("/") && !path.includes("\\") &&
  path.split("/").every((part) => !!part && part !== "." && part !== ".." && !/[\x00-\x1f]/.test(part));

export function ModuleRunDetail({ runId, child }: { runId: string; child: ModuleRunView }) {
  const [showEvents, setShowEvents] = useState(false);
  const label = moduleLabels[child.module] || child.module;
  const result = child.result || {};
  const cause = child.termination_cause || result.termination_cause;
  const counts = verifiedCaseCounts(child);
  const final = new Map((result.case_results || []).map((row) => [row.case_path, row]));
  const missing = new Set(result.missing || []);
  const notRun = new Set(result.not_run || []);
  const report = result.report_status === "ready" && safeReportPath(result.report_path)
    ? `/api/v1/functional/runs/${encodeURIComponent(runId)}/modules/${encodeURIComponent(child.id)}/report/index.html`
    : null;
  return (
    <details className="functional-module">
      <summary><span>{label}</span><Status state={child.state} /><small>{child.env_name}</small></summary>
      <div role="region" aria-label={label} className="functional-module-body">
        <p>阶段：{child.stage || result.stage || "等待执行"}</p>
        <p>环境：{child.env_name}</p>
        {cause && <p>模块终止原因：{cause === 'timeout' ? '达到执行时限' : cause === 'manual' ? '用户停止' : cause}</p>}
        <div className="functional-targets">
          <strong>本次执行机器（提交时快照）</strong>
          {child.execution_targets.length ? child.execution_targets.map((machine) => (
            <p key={`${machine.machine_id}/${machine.ip}/${machine.user}`}>
              {machine.name} · {machine.ip} · {machine.user}
            </p>
          )) : <p>机器身份待确认</p>}
        </div>
        <div className="functional-module-counts">
          {counts
            ? <p>已完成 {counts.completed} / {counts.total} · 通过 {counts.passed} · 失败 {counts.failed} · 跳过 {counts.skipped} · 已知问题 {counts.known_bugs}</p>
            : <p>用例数量待确认</p>}
          <p>套件错误：{typeof result.suite_errors === "number" ? result.suite_errors : "待确认"}</p>
          <p>清理：{result.cleanup_status || "待确认"} · 恢复：{result.recovery_status || "待确认"}</p>
          {!!result.retained_resources?.length && <div>
            <strong>残留资源</strong>
            <ul>{result.retained_resources.map((resource) => <li key={resource.id}>
              {resource.kind} · {resource.name || resource.path || resource.id} · {resource.phase}
            </li>)}</ul>
          </div>}
        </div>
        {child.error && <p role="alert" className="error">{child.error}</p>}
        <div className="functional-actions">
          <button onClick={() => setShowEvents((value) => !value)} aria-expanded={showEvents}>模块日志</button>
          {report ? <a href={report} target="_blank" rel="noreferrer">打开 Allure 报告 ↗</a>
            : <span>{result.report_status ? reportLabels[result.report_status] || "报告状态待确认" : "报告状态待确认"}</span>}
        </div>
        {showEvents && <div className="functional-event-log">
          {child.events.length ? <ol>{child.events.map((event) => <li key={event.seq}>
            {event.time} · {event.stage} · {event.type}
            {event.case_path ? ` · ${event.case_path}` : ""}
            {typeof event.data.message === "string" ? ` · ${event.data.message}` : ""}
          </li>)}</ol> : <p>暂无模块事件</p>}
        </div>}
        <h4>用例结果</h4>
        {child.cases.length ? <ul className="functional-case-results">{child.cases.map((path) => {
          const row = final.get(path);
          return <li key={path}>
            <strong>{path}</strong>
            <span>{row ? `最终：${caseLabels[row.status] || row.status}` : missing.has(path) ? "已启动，结果缺失" : notRun.has(path) ? "未执行" : "结果待确认"}</span>
            {!!result.attempt_records?.length && <ul>{result.attempt_records.filter((item) => item.case_path === path).map((item) =>
              <li key={`${path}/${item.attempt}`}>第 {item.attempt} 次 · {caseLabels[item.status] || item.status}</li>)}</ul>}
          </li>;
        })}</ul> : <p>没有选定用例</p>}
      </div>
    </details>
  );
}
