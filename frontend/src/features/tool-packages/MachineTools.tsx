import { useEffect, useRef, useState } from "react";
import { BadouMascot } from "../../components/BadouMascot";
import { api } from "../../api/client";
import { ToolJob, toolLabels } from "./types";
export function MachineTools({
  machineId,
  canManage,
}: {
  machineId: string;
  canManage: boolean;
}) {
  const [jobs, setJobs] = useState<ToolJob[]>([]);
  const [tool, setTool] = useState("dtt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [logId, setLogId] = useState("");
  const submitted = useRef<ToolJob | null>(null);
  const [reload, setReload] = useState(0);
  const running = jobs.some((j) => j.state === "running");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const rows = await api<ToolJob[]>(`/machines/${machineId}/tool-jobs`);
        if (!Array.isArray(rows)) throw new Error("工具任务列表格式错误");
        if (active) {
          const local = submitted.current;
          if (local && !rows.some((j) => j.id === local.id))
            rows.unshift(local);
          else if (local) submitted.current = null;
          setJobs(rows);
          timer = setTimeout(
            poll,
            rows.some((j) => j.state === "running") ? 1500 : 10000,
          );
        }
      } catch (e) {
        if (active) {
          setError((e as Error).message);
          timer = setTimeout(poll, 10000);
        }
      }
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [machineId, reload]);
  async function start(action: "check" | "auto_install") {
    setBusy(true);
    setError("");
    try {
      const job = await api<ToolJob>(
        `/machines/${machineId}/tool-jobs`,
        "POST",
        { action, ...(action === "auto_install" ? { tool } : {}) },
      );
      job.action = job.action || action;
      submitted.current = job;
      setJobs((rows) => [job, ...rows]);
      setLogId(job.id);
      setReload((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const latest = jobs.find((j) => j.result?.items)?.result;
  const current = jobs.find((j) => j.id === logId) || jobs[0];
  const activeJob = jobs.find((j) => j.state === "running");
  const deployment = jobs.find(
    (j) => j.action === "auto_install" || j.action === "install",
  );
  const statusLabel = (job: ToolJob) => {
    const name = job.action === "check" ? "检查" : "部署";
    return (
      (
        {
          running: `${name}执行中`,
          success: name === "检查" ? "检查完成" : "部署成功",
          failed: `${name}失败`,
          interrupted: `${name}中断，结果未确认`,
        } as Record<string, string>
      )[job.state] || job.state
    );
  };
  const failureReason = (job: ToolJob) =>
    job.error_message ||
    job.result?.error_message ||
    job.log?.trim() ||
    "任务未返回原因，请查看执行日志或重新检查工具状态。";
  return (
    <section className="machine-tools">
      <h2>测试工具</h2>
      {(busy || activeJob) && (
        <div
          className="resource-execution-indicator"
          role="status"
          aria-label="工具执行中"
        >
          <BadouMascot animated size="large" />
          <strong>{activeJob?.phase || "正在提交任务"}</strong>
          <progress
            aria-label="工具任务进度"
            max={100}
            value={activeJob?.progress}
          />
          <span>执行中，请稍候…</span>
          {error && (
            <span className="error">
              状态暂时无法获取：{error}。正在重试，尚不能确认执行结果。
            </span>
          )}
        </div>
      )}
      {deployment && deployment.state !== "running" && (
        <div
          role={deployment.state === "success" ? "status" : "alert"}
          className={deployment.state === "success" ? "" : "error"}
        >
          <strong>{statusLabel(deployment)}</strong>
          {deployment.state !== "success" && (
            <pre
              style={{
                whiteSpace: "pre-wrap",
                maxHeight: "16rem",
                overflow: "auto",
              }}
            >
              {failureReason(deployment)}
            </pre>
          )}
        </div>
      )}
      <p className="muted">
        使用机器登记的 SSH 用户检查和部署。独立安装到该用户的
        ~/.local/share/dingofs-platform/tools，不覆盖已有系统工具。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {canManage && (
        <div className="actions machine-tools-actions">
          <button disabled={busy || running} onClick={() => start("check")}>
            检查工具
          </button>
          <label>
            选择工具
            <select value={tool} onChange={(e) => setTool(e.target.value)}>
              {Object.entries(toolLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary"
            disabled={busy || running}
            onClick={() => start("auto_install")}
          >
            一键部署 / 更新
          </button>
        </div>
      )}
      <p className="muted">
        dtt
        优先由平台机器通过 scp 直传镜像；失败后由目标机器拉取（最多等待10分钟）。其他工具直接从平台机器复制，无需手工打包。
      </p>
      {!latest ? (
        <p>尚未检查工具</p>
      ) : (
        <>
          <p className="muted">
            最近成功检查：{latest.user} · {latest.architecture}
            （当前状态需点击检查更新）
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>工具</th>
                  <th>状态</th>
                  <th>版本</th>
                  <th>实际路径</th>
                  <th>检查详情</th>
                </tr>
              </thead>
              <tbody>
                {latest.items.map((t) => (
                  <tr key={t.tool}>
                    <td>{toolLabels[t.tool] || t.tool}</td>
                    <td>
                      {(
                        {
                          ready: "可用",
                          missing: "未安装",
                          unavailable: "不可用",
                        } as Record<string, string>
                      )[t.status] || t.status}
                    </td>
                    <td>{t.version || "—"}</td>
                    <td>
                      <code>{t.path || "—"}</code>
                    </td>
                    <td>
                      <details>
                        <summary>查看</summary>
                        <pre>{t.details || "无附加信息"}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!!jobs.length && (
        <>
          <label>
            任务记录
            <select
              value={current?.id || ""}
              onChange={(e) => setLogId(e.target.value)}
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.created_at ? new Date(j.created_at).toLocaleString() : ""}{" "}
                  · {j.phase}
                </option>
              ))}
            </select>
          </label>
          {current && (
            <div aria-live="polite">
              <p>
                {current.phase} ·{" "}
                <span>
                  {current.id === deployment?.id
                    ? "部署任务"
                    : statusLabel(current)}
                </span>
              </p>
              {current.id !== deployment?.id &&
                ["failed", "interrupted"].includes(current.state) && (
                  <p role="alert">{failureReason(current)}</p>
                )}
              {current.state === "success" && current.result?.command_path && (
                <p role="status">
                  已配置 dtt 命令。新终端可直接运行 <code>dtt --help</code>
                  ；已有 Bash 终端执行 <code>source ~/.bashrc</code> 后生效。
                </p>
              )}
              {current.result?.method && (
                <p>
                  获取方式：
                  {current.result.method === "registry"
                    ? "目标机器直接拉取镜像"
                    : "平台机器转传"}
                  {current.result.cached
                    ? "（使用已有缓存，未确认仓库最新版本）"
                    : ""}
                </p>
              )}
              {current.state === "running" && (
                <progress
                  aria-label="工具部署进度"
                  max={100}
                  value={current.progress}
                />
              )}
              <details
                open={current.state === "failed" || current.state === "running"}
              >
                <summary>执行命令和日志</summary>
                <pre className="tool-job-log">{current.log || "等待连接…"}</pre>
              </details>
            </div>
          )}
        </>
      )}
    </section>
  );
}
