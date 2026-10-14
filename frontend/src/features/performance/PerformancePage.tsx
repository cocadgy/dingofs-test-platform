import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { BadouMascot } from "../../components/BadouMascot";
import "./performance.css";

import { Tool, Options, Run, Preview } from "./types";
import { ToolParameters } from "./ToolParameters";
import { MatrixForm, defaults, matrixParameters } from "./matrix";
import { ScenarioParameters } from "./ScenarioParameters";
import { ScenarioResults } from "./ScenarioResults";
import { ToolComparisonReports } from "./ToolComparisonReports";
import { ReportCards } from "./ReportCards";
import { TaskTable } from "./TaskTable";
const labels: Record<string, string> = {
  queued: "等待执行",
  running: "运行中",
  cancelling: "正在取消",
  success: "通过",
  failed: "失败",
  cancelled: "已取消",
  unknown: "状态待确认",
};
const active = (state: string) =>
  ["queued", "running", "cancelling", "unknown"].includes(state);
const bytes = (value: number) =>
  value >= 1024 ** 3
    ? (value / 1024 ** 3).toFixed(2) + " GiB"
    : (value / 1024 ** 2).toFixed(2) + " MiB";

export function PerformancePage() {
  const [options, setOptions] = useState<Options>({ machines: [], mounts: [] });
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState(
    window.location.hash.split("/")[2] || "",
  );
  const [reportPath, setReportPath] = useState(
    window.location.hash.split("/").slice(3),
  );
  const [run, setRun] = useState<Run>();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("性能测试 " + new Date().toLocaleString());
  const [machine, setMachine] = useState("");
  const [kind, setKind] = useState("directory");
  const [path, setPath] = useState("");
  const [timeout, setTimeoutMinutes] = useState(120);
  const [cleanupData, setCleanupData] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);
  const [nextTool, setNextTool] = useState<Tool>("fio");
  const [specs, setSpecs] = useState<Record<Tool, MatrixForm>>({
    fio: defaults("fio"),
    elbencho: defaults("elbencho"),
    mdtest: defaults("mdtest"),
  });
  const [sizes, setSizes] = useState<Record<Tool, string>>({
    fio: "files",
    elbencho: "files",
    mdtest: "files",
  });
  const [preview, setPreview] = useState<Preview>();
  const [previewKey, setPreviewKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  let parameterError = "";
  let tests: ReturnType<typeof matrixParameters>[] = [];
  try {
    tests = tools.map((tool) => matrixParameters(specs[tool], sizes[tool]));
  } catch (e) {
    parameterError = (e as Error).message;
  }
  const payload = {
    name,
    machine_id: machine,
    target_kind: kind,
    target_path: path,
    timeout_minutes: timeout,
    cleanup_data: cleanupData,
    tests,
  };
  const key = JSON.stringify({ payload, specs, sizes, tools });
  useEffect(() => {
    let live = true;
    api<Options>("/performance/options")
      .then((v) => {
        if (live) setOptions(v);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const v = await api<Run[]>("/performance/runs");
        if (live) setRuns(v);
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    const sync = () => {
      setSelected(window.location.hash.split("/")[2] || "");
      setReportPath(window.location.hash.split("/").slice(3));
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  useEffect(() => {
    if (!selected) {
      setRun(undefined);
      return;
    }
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    setRun(undefined);
    async function poll() {
      try {
        const v = await api<Run>(
          "/performance/runs/" + encodeURIComponent(selected),
        );
        if (live) {
          setRun(v);
          if (active(v.state)) timer = setTimeout(poll, 2000);
        }
      } catch (e) {
        if (live) {
          setError((e as Error).message);
          timer = setTimeout(poll, 5000);
        }
      }
    }
    poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [selected]);
  function change(
    tool: Tool,
    key: keyof MatrixForm,
    value: string | string[] | boolean[],
  ) {
    setSpecs((s) => ({ ...s, [tool]: { ...s[tool], [key]: value } }));
  }
  async function prepare(e: React.FormEvent) {
    e.preventDefault();
    if (parameterError) {
      setError(parameterError);
      return;
    }
    setError("");
    setBusy(true);
    try {
      const p = await api<Preview>("/performance/preview", "POST", payload);
      setPreview(p);
      setPreviewKey(key);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    if (previewKey !== key) return;
    setBusy(true);
    setError("");
    try {
      const v = await api<Run>("/performance/runs", "POST", payload);
      setRuns((r) => [v, ...r]);
      setShowForm(false);
      setPreview(undefined);
      window.location.hash = "#/performance/" + v.id;
      setSelected(v.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function rerun(original: Run) {
    if (
      !confirm(
        `使用「${original.name}」的原参数重新运行？将创建新任务，保留原报告。`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const next = await api<Run>(
        "/performance/runs/" + original.id + "/rerun",
        "POST",
      );
      setRuns((rows) => [next, ...rows]);
      window.location.hash = "#/performance/" + next.id;
      setSelected(next.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!run || !confirm("确认停止本任务？已有测试数据和报告将保留。")) return;
    setBusy(true);
    try {
      setRun(await api<Run>("/performance/runs/" + run.id + "/cancel", "POST"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const reportPage = reportPath[0] === "reports";
  const reportScene = reportPath[1] || "";
  const currentMachine = options.machines.find((m) => m.id === machine);
  return (
    <section className="performance-page">
      <div className="section-title">
        <div>
          <h1>
            {showForm
              ? "新建性能测试"
              : selected
                ? reportPage
                  ? "性能测试报告"
                  : "性能测试详情"
                : "性能测试"}
          </h1>
          <p className="muted">
            单客户端存储性能 · fio / elbencho / mdtest ·
            多参数组合顺序执行，可选完成后清理数据
          </p>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={() => {
            if (!showForm && !selected) {
              setTools([]);
              setNextTool("fio");
            }
            setShowForm(!showForm && !selected);
            setSelected("");
            setRun(undefined);
            setPreview(undefined);
            window.location.hash = "#/performance";
            setError("");
          }}
        >
          {showForm || selected ? "返回" : "新建测试"}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && (
        <div
          className="resource-execution-indicator"
          role="status"
          aria-label="正在处理性能任务"
        >
          <BadouMascot animated size="large" />
          <strong>正在处理，请稍候…</strong>
        </div>
      )}
      {showForm && (
        <form className="panel" onSubmit={prepare}>
          <h2>配置测试</h2>
          <fieldset disabled={busy}>
            <div className="form-grid">
              <label>
                任务名称
                <input
                  required
                  maxLength={120}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                目标机器
                <select
                  required
                  value={machine}
                  onChange={(e) => {
                    setMachine(e.target.value);
                    setPath("");
                  }}
                >
                  <option value="">请选择机器</option>
                  {options.machines.map((m) => (
                    <option key={m.id} value={m.id} disabled={m.maintenance}>
                      {m.name} · {m.ssh_user}@{m.address}
                      {m.maintenance ? "（维护中）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                测试目标
                <select
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value);
                    setPath("");
                  }}
                >
                  <option value="directory">普通目录 / 磁盘文件性能</option>
                  <option value="mount">已挂载的文件系统目录</option>
                </select>
              </label>
              <label>
                目标目录
                <input
                  required
                  aria-label="目标目录"
                  placeholder="例如 /mnt/disk1/benchmark"
                  value={path}
                  list="performance-mounts"
                  onChange={(e) => setPath(e.target.value)}
                />
                <datalist id="performance-mounts">
                  {options.mounts
                    .filter((m) => m.machine_id === machine && m.path)
                    .map((m) => (
                      <option key={m.id} value={m.path}>
                        {m.name}
                      </option>
                    ))}
                </datalist>
                <small>
                  普通目录不存在时自动创建，权限不足时尝试 sudo
                  创建并授权；挂载目录必须已挂载。
                </small>
              </label>
              <label>
                任务总超时（分钟）
                <input
                  type="number"
                  min={1}
                  max={1440}
                  required
                  value={timeout}
                  onChange={(e) => setTimeoutMinutes(+e.target.value)}
                />
              </label>
            </div>
            <label className="performance-cleanup-option">
              <input
                type="checkbox"
                checked={cleanupData}
                onChange={(e) => setCleanupData(e.target.checked)}
              />
              测试完成后清理测试数据
            </label>
            <p className="muted">
              仅在全部场景通过后清理本任务数据目录，保留报告与日志；失败、取消或超时保留数据。
            </p>
            {currentMachine && (
              <p>
                执行用户：{currentMachine.ssh_user}。未安装 dtt 时，请先到{" "}
                <a href={"#/machines/" + machine}>机器详情 → 测试工具</a> 部署。
              </p>
            )}
            <div className="performance-tools">
              <label>
                选择工具
                <select
                  aria-label="选择工具"
                  value={nextTool}
                  onChange={(e) => setNextTool(e.target.value as Tool)}
                >
                  {(["fio", "elbencho", "mdtest"] as Tool[]).map((tool) => (
                    <option
                      key={tool}
                      value={tool}
                      disabled={tools.includes(tool)}
                    >
                      {tool}
                      {tools.includes(tool) ? "（已添加）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={tools.includes(nextTool)}
                onClick={() => {
                  if (tools.includes(nextTool)) return;
                  setSpecs((s) => ({ ...s, [nextTool]: defaults(nextTool) }));
                  setSizes((s) => ({ ...s, [nextTool]: "files" }));
                  setTools((t) => [nextTool, ...t]);
                  setNextTool((["fio","elbencho","mdtest"] as Tool[]).find(t=>t!==nextTool && !tools.includes(t)) || nextTool);
                }}
              >
                添加工具
              </button>
            </div>
            {!tools.length && (
              <p className="muted">请先添加测试工具，再配置参数。</p>
            )}
            {tools.map((tool) => (
              <ToolParameters
                key={tool}
                catalog={options.mdtest_options}
                tool={tool}
                s={specs[tool]}
                sizeMode={sizes[tool]}
                change={change}
                onRemove={() => {
                  setTools((t) => t.filter((item) => item !== tool));
                  setNextTool(tool);
                }}
                onSizeMode={(value) =>
                  setSizes((s) => ({ ...s, [tool]: value }))
                }
              />
            ))}
            <p className="muted">
              文件数量是每个场景的全局总数，不按并发倍增。最多 256
              个候选组合；读比例仅用于混合读写。同一场景的成功轮次取均值，各场景使用独立数据。普通场景失败后继续其余场景；总超时或取消会停止整批任务。
            </p>
            <button disabled={!tools.length || !machine}>预览执行计划</button>
            {preview && previewKey === key && (
              <div className="performance-preview">
                <h3>确认执行计划</h3>
                <p>
                  测试数据：
                  {cleanupData
                    ? "全部通过后自动清理；失败或取消保留"
                    : "保留，不自动清理"}
                </p>
                <p>
                  测试期间的数据集总量：
                  <strong>{bytes(preview.total_bytes)}</strong>
                  。在目标目录下新建独立测试子目录，不覆盖原有文件。mdtest 创建空文件，0 B 不代表不占用磁盘：仍消耗 inode 和元数据空间。
                </p>
                <p>
                  共 {preview.scene_count ?? preview.tests.length}{" "}
                  个场景，按下表顺序执行。
                </p>
                <div className="table-scroll performance-scene-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>场景</th>
                        <th>参数组合</th>
                        <th>执行命令</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.tests.map((t, index) => (
                        <tr key={t.id || index}>
                          <td>
                            {index + 1} · {t.tool}
                          </td>
                          <td>
                            {t.parameters && (
                              <ScenarioParameters spec={t.parameters} />
                            )}
                          </td>
                          <td>
                            <details>
                              <summary>查看命令</summary>
                              <pre>{t.command}</pre>{t.mdtest_command && <><strong>自定义场景中的命令</strong><pre>{t.mdtest_command}</pre></>}
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" className="primary" onClick={start}>
                  确认并开始测试
                </button>
              </div>
            )}
          </fieldset>
        </form>
      )}
      {!showForm && !selected && (
        <TaskTable
          runs={runs}
          selected={selected}
          busy={busy}
          onRerun={rerun}
        />
      )}
      {!showForm && selected && !run && <p role="status">正在读取测试详情…</p>}
      {!showForm && run && (
        <div className="panel">
          <div className="section-title">
            <h2>{run.name}</h2>
            {run.can_manage && active(run.state) && (
              <button
                disabled={busy || run.cancel_requested === true}
                onClick={cancel}
              >
                取消测试
              </button>
            )}
          </div>
          {!reportPage && (
            <>
              <p>
                <span className={"performance-state " + run.state}>
                  {labels[run.state]}
                </span>{" "}
                · {run.phase}
              </p>
              <progress aria-label="测试进度" max={100} value={run.progress} />
              <p>
                {run.snapshot.connection[2]}@{run.snapshot.connection[0]} ·{" "}
                {run.snapshot.target_path}
              </p>
              <p>
                已耗时：
                {Math.max(
                  0,
                  Math.round(
                    (new Date(run.finished_at || Date.now()).getTime() -
                      new Date(run.created_at).getTime()) /
                      1000,
                  ),
                )}{" "}
                秒 · 截止时间：{new Date(run.deadline).toLocaleString()}
              </p>
              <p>
                数据清理：
                {run.snapshot.cleanup_data
                  ? "全部场景通过后自动清理"
                  : "保留测试数据"}
              </p>
              {run.remote_root && (
                <p className="muted">远端任务及完整日志：{run.remote_root}</p>
              )}
              {run.error && (
                <p className="error" role="alert">
                  {run.error}
                </p>
              )}
              <details>
                <summary>执行命令和实时日志（显示最近128KiB）</summary>
                <pre className="performance-log">
                  {run.log || "等待远端任务输出…"}
                </pre>
              </details>
            </>
          )}
          {reportPage && <a href={"#/performance/" + run.id}>返回任务详情</a>}
          <h3>测试报告</h3>
          {!Object.keys(run.reports).length && (
            <p>
              运行时展示逐场景进度，任务结束后可打开各场景报告；不同参数组合分别统计。
            </p>
          )}
          {reportScene ? (
            run.reports[reportScene] ? (
              <>
                <a href={"#/performance/" + run.id + "/reports"}>
                  返回工具汇总报告
                </a>
                <ReportCards
                  key={run.id + reportScene}
                  run={{
                    ...run,
                    reports: { [reportScene]: run.reports[reportScene] },
                  }}
                />
              </>
            ) : (
              <p role="alert">报告不存在或尚未生成。</p>
            )
          ) : reportPage ? (
            <ToolComparisonReports key={run.id} run={run} />
          ) : (
            <>
              <a href={"#/performance/" + run.id + "/reports"}>
                查看工具汇总报告
              </a>
              <ScenarioResults key={run.id} run={run} />
            </>
          )}
        </div>
      )}
    </section>
  );
}
