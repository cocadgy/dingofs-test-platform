import { useState } from "react";
import { Run, Status, elapsed, active, moduleLabels } from "./types";
export function RunDetail({
  run,
  busy,
  onStop,
  onRerun,
}: {
  run: Run;
  busy: boolean;
  onStop: () => void;
  onRerun: (failed: boolean) => void;
}) {
  const [tab, setTab] = useState("results");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [query, setQuery] = useState("");
  const cases = run.result?.cases || [];
  const total = Object.values(run.snapshot.selected).reduce(
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
          {active(run.state) ? (
            <button
              disabled={busy || run.state === "cancelling"}
              onClick={onStop}
            >
              停止测试（当前用例结束后生效）
            </button>
          ) : (
            <>
              <button disabled={busy} onClick={() => onRerun(false)}>
                重跑全部
              </button>
              <button
                disabled={busy || !failed.length}
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
