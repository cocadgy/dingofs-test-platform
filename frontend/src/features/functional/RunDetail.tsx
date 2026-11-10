import { useState } from "react";
import { Run, Status, elapsed, active, moduleLabels, verifiedCaseCounts } from "./types";
import { ModuleRunDetail } from "./ModuleRunDetail";

function V2RunDetail({ run, busy, onStop, onRerun, onVerifyResources, verification }: {
  run: Run; busy: boolean; onStop: () => void; onRerun: (failed: boolean) => void;
  onVerifyResources?: () => void; verification?: string;
}) {
  const children = [...(run.children || [])].sort((a, b) => a.position - b.position);
  const totals = children.map(verifiedCaseCounts);
  const allCountsKnown = children.length > 0 && totals.every((row) => row !== null);
  const sum = (key: "passed" | "failed" | "skipped" | "known_bugs" | "completed") =>
    allCountsKnown ? totals.reduce((value, row) => value + (row?.[key] || 0), 0) : null;
  const selected = children.reduce((value, child) => value + child.cases.length, 0);
  const completed = sum("completed");
  const failures = sum("failed");
  const suiteErrors = allCountsKnown && children.every((child) => typeof child.result.suite_errors === "number")
    ? children.reduce((value, child) => value + (child.result.suite_errors || 0), 0) : null;
  const canManage = run.can_manage === true;
  const canRerun = canManage && children.length > 0 &&
    ["success", "failed", "cancelled"].includes(run.state) &&
    children.every((child) => !["unknown", "needs_attention", "cancelling"].includes(child.state) &&
      child.execution_targets?.length > 0 && child.execution_targets.every((machine) =>
        !!machine.machine_id && !!machine.name && !!machine.ip && !!machine.user));
  return <>
    <section className="functional-card">
      <div className="functional-detail-title"><h2>{run.name}</h2><Status state={run.state} /></div>
      <p>{run.snapshot.cluster_name || run.snapshot.cluster_id || "—"} · 耗时 {elapsed(run)}</p>
      <div className="functional-stats">
        <div><strong>{sum("passed") ?? "—"}</strong><span>通过</span></div>
        <div className={failures ? "has-failure" : ""}><strong>{failures ?? "—"}</strong><span>失败</span></div>
        <div><strong>{completed === null ? "—" : Math.max(0, selected - completed)}</strong><span>未完成</span></div>
        <div><strong>{completed === null ? `— / ${selected}` : `${completed} / ${selected}`}</strong><span>已完成用例</span></div>
      </div>
      <p>跳过 {sum("skipped") ?? "—"} · 已知问题 {sum("known_bugs") ?? "—"} · 套件错误 {suiteErrors ?? "—"}</p>
      {completed !== null && selected > 0 && <progress aria-label="用例完成进度" max={selected} value={completed} />}
      <p>当前阶段：{run.phase || "等待执行"}</p>
      {run.error && <p role="alert" className="error">{run.error}</p>}
      <div className="functional-actions">
        {canManage && onVerifyResources && ["success", "failed", "cancelled", "needs_attention"].includes(run.state) &&
          <button disabled={busy} onClick={onVerifyResources}>重新检查残留资源</button>}
        {canManage && ["queued", "running"].includes(run.state) && <button disabled={busy} onClick={onStop}>停止测试（当前用例结束后生效）</button>}
        {canRerun && <>
          <button disabled={busy} onClick={() => onRerun(false)}>重跑全部</button>
          <button disabled={busy || !failures} onClick={() => onRerun(true)}>重跑失败用例</button>
        </>}
        <a href="#/start/functional">返回引导配置</a>
      </div>
      {verification && <p role="status">{verification}</p>}
    </section>
    <section className="functional-card">
      <h3>模块进度与结果</h3>
      {children.length ? children.map((child) => <ModuleRunDetail key={child.id} runId={run.id} child={child} />)
        : <p className="functional-empty">模块详情暂不可用，请稍后刷新。</p>}
    </section>
    <section className="functional-card">
      <h3>任务日志</h3>
      <pre className="functional-log">{run.log || "等待输出…"}</pre>
    </section>
  </>;
}
export function RunDetail({
  run,
  busy,
  onStop,
  onRerun,
  onVerifyResources,
  verification,
}: {
  run: Run;
  busy: boolean;
  onStop: () => void;
  onRerun: (failed: boolean) => void;
  onVerifyResources?: () => void;
  verification?: string;
}) {
  const [tab, setTab] = useState("results");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [query, setQuery] = useState("");
  if (run.version === 2) return <V2RunDetail run={run} busy={busy} onStop={onStop} onRerun={onRerun}
    onVerifyResources={onVerifyResources} verification={verification} />;
  const cases = run.result?.cases || [];
  const total = Object.values(run.snapshot.selected || {}).reduce(
    (n, rows) => n + rows.length,
    0,
  );
  const failed = cases.filter((c) => ["FAIL", "ERROR"].includes(c.status));
  const passed = cases.filter((c) => c.status === "PASS").length;
  const rest = Math.max(0, total - cases.length);
  const rows = [...cases]
    .filter((c) => !onlyFailed || ["FAIL", "ERROR"].includes(c.status))
    .sort(
      (a, b) =>
        Number(["FAIL", "ERROR"].includes(b.status)) -
        Number(["FAIL", "ERROR"].includes(a.status)),
    );
  return (
    <>
      <section className="functional-card">
        <div className="functional-detail-title">
          <h2>{run.name}</h2>
          <Status state={run.state} />
        </div>
        <p>
          {run.snapshot.cluster_name || "—"} · 耗时 {elapsed(run)}
        </p>
        <div className="functional-stats">
          <div>
            <strong>{passed}</strong>
            <span>通过</span>
          </div>
          <div className={failed.length ? "has-failure" : ""}>
            <strong>{failed.length}</strong>
            <span>失败 / 错误</span>
          </div>
          <div>
            <strong>{rest}</strong>
            <span>{active(run.state) ? "待执行" : "未执行"}</span>
          </div>
          <div>
            <strong>
              {cases.length} / {total}
            </strong>
            <span>已完成用例</span>
          </div>
        </div>
        <progress
          aria-label="用例完成进度"
          max={Math.max(total, 1)}
          value={cases.length}
        />
        <p>
          当前阶段：
          {active(run.state) && cases.length === total && total
            ? "用例执行完毕，正在清理或生成报告"
            : run.phase || "等待执行"}
        </p>
        {run.error && (
          <p role="alert" className="error">
            {run.error}
          </p>
        )}
        <div className="functional-actions">
          {["queued", "running", "cancelling", "unknown"].includes(run.state) ? (
            <button
              disabled={busy || run.state === "cancelling"}
              onClick={onStop}
            >
              停止测试（当前用例结束后生效）
            </button>
          ) : (
            <>
              <button disabled onClick={() => onRerun(false)}>
                重跑全部
              </button>
              <button
                disabled
                onClick={() => onRerun(true)}
              >
                重跑失败用例
              </button>
              {cases.length > 0 && (
                <a
                  target="_blank"
                  rel="noreferrer"
                  href={`/api/v1/functional/runs/${encodeURIComponent(run.id)}/report/index.html`}
                >
                  打开 Allure 报告 ↗
                </a>
              )}
            </>
          )}
          {!active(run.state) && <span className="functional-muted">历史任务只读</span>}
        </div>
      </section>
      <section className="functional-card">
        <nav className="functional-tabs" aria-label="任务详情">
          <button
            aria-pressed={tab === "results"}
            onClick={() => setTab("results")}
          >
            用例结果
          </button>
          <button aria-pressed={tab === "log"} onClick={() => setTab("log")}>
            执行日志
          </button>
        </nav>
        {tab === "results" ? (
          <>
            <div className="functional-toolbar">
              <label className="functional-check">
                <input
                  type="checkbox"
                  checked={onlyFailed}
                  onChange={(e) => setOnlyFailed(e.target.checked)}
                />
                只看失败（{failed.length}）
              </label>
              <span>失败用例优先显示</span>
            </div>
            <div className="functional-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>结果</th>
                    <th>模块</th>
                    <th>用例</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c, i) => (
                    <tr key={`${c.module}/${c.case}/${i}`}>
                      <td>
                        <span
                          className={`functional-badge state-${c.status === "PASS" ? "success" : ["FAIL", "ERROR"].includes(c.status) ? "failed" : "unknown"}`}
                        >
                          {(
                            {
                              PASS: "通过",
                              FAIL: "失败",
                              ERROR: "错误",
                              SKIP: "跳过",
                            } as Record<string, string>
                          )[c.status] || c.status}
                        </span>
                      </td>
                      <td>{moduleLabels[c.module] || c.module}</td>
                      <td>{c.case}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!rows.length && (
              <p className="functional-empty">
                {onlyFailed ? "暂无失败用例" : "等待用例结果…"}
              </p>
            )}
          </>
        ) : (
          <>
            <input
              type="search"
              aria-label="筛选日志"
              placeholder="输入关键字筛选当前已读取的日志"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <p className="functional-muted">
              显示服务端保留的最近日志；完整结果请查看 Allure 报告。
            </p>
            <pre className="functional-log">
              {query
                ? (run.log || "")
                    .split("\n")
                    .filter((line) =>
                      line.toLowerCase().includes(query.toLowerCase()),
                    )
                    .join("\n") || "没有匹配日志"
                : run.log || "等待输出…"}
            </pre>
          </>
        )}
      </section>
    </>
  );
}
