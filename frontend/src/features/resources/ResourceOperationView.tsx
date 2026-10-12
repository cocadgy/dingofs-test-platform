import { LogFileTable } from "../remote/LogFileTable";
import type { RemoteFile } from "../remote/types";
import { visibleFilesystemName } from "./filesystemOptions";
import { memo, useEffect, useState } from "react";
import { LazyDetails } from "./LazyDetails";
import { api } from "../../api/client";
import { pendingStates, stateLabels, type ResourceOperation } from "./types";

export function StructuredResult({ value }: { value: unknown }) {
  if (value == null) return <span>—</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <p className="muted">无记录</p>;
    if (
      value.every(
        (row) => row && typeof row === "object" && !Array.isArray(row),
      )
    ) {
      const keys = [...new Set(value.flatMap((row) => Object.keys(row)))];
      return (
        <div className="resource-table-scroll">
          <table>
            <thead>
              <tr>
                {keys.map((key) => (
                  <th key={key}>{key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, index) => (
                <tr key={index}>
                  {keys.map((key) => (
                    <td key={key}>
                      <StructuredResult value={row[key]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return (
      <ul>
        {value.map((item, index) => (
          <li key={index}>
            <StructuredResult value={item} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object")
    return (
      <dl className="resource-result-fields">
        {Object.entries(value).map(([key, item]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>
              <StructuredResult value={item} />
            </dd>
          </div>
        ))}
      </dl>
    );
  return <span className="resource-result-text">{String(value)}</span>;
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}
function bytes(value: unknown) {
  const n =
    typeof value === "number"
      ? value
      : typeof value === "string" && /^\d+$/.test(value)
        ? Number(value)
        : NaN;
  if (!Number.isFinite(n) || n < 0) return String(value ?? "—");
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index =
    n > 0
      ? Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1)
      : 0;
  return `${Number((n / 1024 ** index).toFixed(2))} ${units[index]}`;
}
function QueryResult({ value, failed }: { value: unknown; failed: boolean }) {
  const envelope = object(value);
  if (Array.isArray(envelope?.executed_commands)) {
    const { executed_commands, ...rest } = envelope;
    return (
      <div>
        <h4>实际执行命令</h4>
        <p className="muted">
          在目标机器、目标用户环境中执行；重复的状态查询合并显示。敏感参数已隐藏。
        </p>
        {!executed_commands.length && (
          <p>本步骤没有执行外部命令或发送进程信号。</p>
        )}
        {executed_commands.map((item, index) => {
          const entry = object(item);
          if (!entry) return null;
          return (
            <section key={index}>
              <p>
                命令 {index + 1} ·{" "}
                {entry.status === "started" ? "已启动执行" : "尝试启动"}
                {Number(entry.count) > 1 ? ` · 执行 ${entry.count} 次` : ""}
              </p>
              <pre
                className="resource-output"
                aria-label={`实际命令 ${index + 1}`}
              >
                {String(entry.command || "")}
              </pre>
              {entry.equivalent === true && <p>等价命令；实际通过 {String(entry.method)} 系统调用发送 {String(entry.signal || "SIGTERM")}。</p>}
              {entry.executable != null && (
                <p className="muted">
                  程序路径：<code>{String(entry.executable)}</code>
                </p>
              )}
              {entry.truncated === true && <p>命令过长，展示内容已截断。</p>}
            </section>
          );
        })}
        <QueryResult value={rest} failed={failed} />
      </div>
    );
  }
  const diagnostics = object(envelope?.diagnostics);
  if (diagnostics) {
    const files = Array.isArray(diagnostics.files) ? diagnostics.files : [];
    const { diagnostics: _details, ...summary } = envelope!;
    return (
      <div>
        <StructuredResult value={summary} />
        <h4>进程日志</h4>
        <p>
          远端日志目录：<code>{String(diagnostics.log_dir || "未提供")}</code>
        </p>
        <p className="muted">
          失败时采集的日志末尾快照，每个文件最多 80 行 / 16 KiB，最多 6 个文件。
        </p>
        {diagnostics.error != null && (
          <p role="alert">日志读取失败：{String(diagnostics.error)}</p>
        )}
        {diagnostics.truncated === true && (
          <p>仅展示部分日志文件，请到远端日志目录查看完整记录。</p>
        )}
        {!files.length && diagnostics.error == null && (
          <p>日志目录尚未生成日志文件。</p>
        )}
        {files.map((item, index) => {
          const log = object(item);
          if (!log) return null;
          return (
            <section key={index}>
              <strong>{String(log.filename || "日志")}</strong>
              {log.truncated === true && (
                <p className="muted">内容已截断，仅展示末尾。</p>
              )}
              {log.error != null ? (
                <p>读取失败：{String(log.error)}</p>
              ) : (
                <pre
                  className="resource-output"
                  aria-label={`进程日志 ${String(log.filename)}`}
                >
                  {String(log.text || "（空日志）")}
                </pre>
              )}
            </section>
          );
        })}
      </div>
    );
  }

  if (!failed && typeof envelope?.effective_port === "number") {
    const adjusted =
      typeof envelope.planned_port === "number" &&
      envelope.planned_port !== envelope.effective_port;
    return (
      <div>
        <p>
          本次检查 / 使用的监听端口：<strong>{envelope.effective_port}</strong>
        </p>
        {adjusted && (
          <p>
            检查时的端口 {String(envelope.planned_port)}{" "}
            已被占用，启动前自动调整为 {envelope.effective_port}。
          </p>
        )}
        <LazyDetails summary="成员与端口详情">
          <StructuredResult value={value} />
        </LazyDetails>
      </div>
    );
  }
  const result = object(envelope?.result);
  const body = result ?? envelope;
  const fs = object(body?.fs_info);
  if (fs) {
    const extra = object(fs.extra);
    const s3 = object(extra?.s3_info);
    const rados = object(extra?.rados_info);
    const partition = object(
      object(object(fs.partition_policy)?.Partition)?.ParentHash,
    );
    const mounts = fs.mount_points ?? fs.mountPoints;
    // dingo JSON omits empty protobuf lists; verbose prints mountPoints: [].
    const mountCount = Array.isArray(mounts)
      ? mounts.length
      : (fs.mount_num ??
        fs.mountNum ??
        (!failed && mounts == null ? 0 : undefined));
    const fields: [string, unknown][] = [
      ["FSID", fs.fs_id],
      ["文件系统名称", fs.fs_name],
      ["状态", fs.status === 1 ? "NORMAL" : fs.status],
      [
        "块大小",
        fs.block_size == null
          ? undefined
          : `${bytes(fs.block_size)} (${fs.block_size} B)`,
      ],
      [
        "分块大小",
        fs.chunk_size == null
          ? undefined
          : `${bytes(fs.chunk_size)} (${fs.chunk_size} B)`,
      ],
      ["MDS 数量", partition?.expect_mds_num],
      ["存储类型", s3 ? "S3" : rados ? "RADOS" : undefined],
      [
        "存储地址",
        s3 ? [s3.endpoint, s3.bucketname].filter(Boolean).join("/") : undefined,
      ],
      ["挂载数", mountCount],
      ["UUID", fs.uuid],
      ["所有者", fs.owner],
    ];
    return (
      <div className="resource-query-result">
        <h4>文件系统详情</h4>
        <dl className="resource-result-fields" aria-label="文件系统详情字段">
          {fields.map(([label, item]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{item == null ? "未返回" : String(item)}</dd>
            </div>
          ))}
        </dl>
        <LazyDetails summary="完整字段">
          <StructuredResult value={fs} />
        </LazyDetails>
        <LazyDetails summary="响应详情" open={failed}>
          <StructuredResult value={value} />
        </LazyDetails>
      </div>
    );
  }
  const allRows = body?.fs_infos;
  if (!Array.isArray(allRows) || !allRows.every((row) => object(row)))
    return <StructuredResult value={value} />;
  const rows = allRows.filter((row) => visibleFilesystemName(row.fs_name));
  const { fs_infos: _rows, ...metadata } = body!;
  const { result: _result, ...response } = result ? envelope! : {};
  const diagnostic = result ? { ...response, ...metadata } : metadata;
  const responseError = object(envelope?.error);
  const hasError =
    failed ||
    (responseError?.code != null && String(responseError.code) !== "0");
  return (
    <div className="resource-query-result">
      <h4>
        文件系统列表 <small>（{rows.length} 个）</small>
      </h4>
      {!rows.length ? (
        <p className="muted">暂无文件系统</p>
      ) : (
        <div className="resource-table-scroll">
          <table className="resource-summary-table" aria-label="文件系统列表">
            <thead>
              <tr>
                {[
                  "ID",
                  "文件系统名称",
                  "状态",
                  "所有者",
                  "容量",
                  "块大小",
                  "详情",
                ].map((name) => (
                  <th key={name}>{name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {[row.fs_id, row.fs_name, row.status, row.owner].map(
                    (cell, i) => (
                      <td key={i}>
                        <StructuredResult value={cell} />
                      </td>
                    ),
                  )}
                  <td title={String(row.capacity ?? "")}>
                    {bytes(row.capacity)}
                  </td>
                  <td title={String(row.block_size ?? "")}>
                    {bytes(row.block_size)}
                  </td>
                  <td>
                    <LazyDetails
                      summary="完整字段"
                      className="resource-row-details"
                    >
                      <StructuredResult value={row} />
                    </LazyDetails>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {Object.keys(diagnostic).length > 0 && (
        <LazyDetails
          summary="响应详情"
          open={hasError}
          className="resource-diagnostics"
        >
          <StructuredResult value={diagnostic} />
        </LazyDetails>
      )}
    </div>
  );
}

export const ResourceOperationView = memo(function ResourceOperationView({
  operation,
  label,
  canManage,
  onChange,
  onOpenLog,
  summarized = false,
  renderDetails = true,
}: {
  operation: ResourceOperation;
  label: string;
  canManage: boolean;
  onChange: (operation: ResourceOperation) => void;
  onOpenLog?: (operation: ResourceOperation, filename: string) => void;
  summarized?: boolean;
  renderDetails?: boolean;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollAttempt, setPollAttempt] = useState(0);
  useEffect(() => {
    setPassword("");
    setError("");
  }, [operation.id, operation.challenge]);
  useEffect(() => {
    if (!canManage) setPassword("");
  }, [canManage]);
  useEffect(() => {
    if (!canManage || !["pending", "running"].includes(operation.state)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<ResourceOperation>(
          `/resource-operations/${encodeURIComponent(operation.id)}`,
        );
        if (!active) return;
        onChange(next);
        if (["pending", "running"].includes(next.state))
          timer = setTimeout(poll, 1200);
      } catch (e) {
        if (active)
          setError(
            `${(e as Error).message}。进度查询已停止，请刷新进度核实；不会重新执行命令。`,
          );
      }
    };
    timer = setTimeout(poll, 400);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [operation.id, operation.state, onChange, pollAttempt, canManage]);
  async function authenticate(e: React.FormEvent) {
    e.preventDefault();
    if (!canManage || busy || !operation.challenge) return;
    const secret = password;
    setPassword("");
    setBusy(true);
    setError("");
    try {
      onChange(
        await api<ResourceOperation>(
          `/resource-operations/${encodeURIComponent(operation.id)}/authenticate`,
          "POST",
          { challenge: operation.challenge, password: secret },
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!canManage || busy) return;
    setPassword("");
    setBusy(true);
    setError("");
    try {
      onChange(
        await api<ResourceOperation>(
          `/resource-operations/${encodeURIComponent(operation.id)}/cancel`,
          "POST",
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  // Hidden history entries still own polling and credential cleanup.
  if (!renderDetails) return null;
  const active = pendingStates.includes(operation.state);
  const abnormal = [
    "failed",
    "cancelled",
    "interrupted",
    "unknown",
    "partial",
  ].includes(operation.state);
  const steps = operation.result?.steps || [];
  const batchKey = ["cache.delete_batch", "cache.stop"].includes(
    operation.action,
  )
    ? "member_id"
    : "fs_name";
  const batchTargets =
    operation.payload?.[batchKey === "member_id" ? "member_ids" : "fs_names"];
  return (
    <article className="resource-operation" aria-label={`${label}操作记录`}>
      {!summarized && (
        <div className="resource-operation-heading">
          <strong>{label}</strong>
          <span className={`badge ${abnormal ? "error" : ""}`}>
            {stateLabels[operation.state] || operation.state}
          </span>
          <small>{operation.id}</small>
        </div>
      )}
      {summarized ? (
        <details className="resource-execution-info">
          <summary>执行信息</summary>
          <dl className="resource-result-fields">
            <div>
              <dt>记录 ID</dt>
              <dd>{operation.id}</dd>
            </div>
            {operation.machine_name && (
              <div>
                <dt>执行机器</dt>
                <dd>{operation.machine_name}</dd>
              </div>
            )}
            {operation.target_user && (
              <div>
                <dt>执行用户</dt>
                <dd>{operation.target_user}</dd>
              </div>
            )}
          </dl>
        </details>
      ) : (
        <p className="resource-operation-meta">
          {operation.created_at && (
            <time dateTime={operation.created_at}>
              {new Date(operation.created_at).toLocaleString()}
            </time>
          )}
          {operation.machine_name && (
            <span>执行机器：{operation.machine_name}</span>
          )}
          {operation.target_user && (
            <span>执行用户：{operation.target_user}</span>
          )}
        </p>
      )}
      {operation.phase === "waiting_offline" && active && (
        <p role="status">已发送停止操作，正在等待成员离线（最多 180 秒）…</p>
      )}
      {operation.message && <p>{operation.message}</p>}
      {operation.error_code && (
        <p className="error">错误代码：{operation.error_code}</p>
      )}
      {abnormal && (
        <p className="error">
          操作未正常完成，可能已有部分变更或结果未知。请核实远端状态；取消等待不会撤销已经执行的操作。
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {error && ["pending", "running"].includes(operation.state) && (
        <button
          type="button"
          onClick={() => {
            setError("");
            setPollAttempt((value) => value + 1);
          }}
        >
          刷新进度
        </button>
      )}
      {operation.state === "needs_password" &&
        canManage &&
        operation.challenge && (
          <form onSubmit={authenticate} className="resource-auth">
            <h4>用户切换认证</h4>
            <p>
              执行机器：{operation.machine_name} · 目标用户：
              {operation.target_user}
            </p>
            <p>
              需要验证账号：<strong>{operation.auth_account}</strong>
            </p>
            <p className="muted">
              密码仅用于本次操作，提交后清空；这里不是网站登录密码。
            </p>
            <label>
              认证密码
              <input
                type="password"
                required
                disabled={busy}
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button className="primary" disabled={busy}>
              验证并继续
            </button>
          </form>
        )}
      {operation.state === "needs_trust" && (
        <p className="error">
          请先在机器详情核验 SSH 指纹，再明确发起新的操作。
        </p>
      )}
      {active && (
        <button type="button" disabled={!canManage || busy} onClick={cancel}>
          取消等待
        </button>
      )}
      {operation.payload && Object.keys(operation.payload).length > 0 && (
        <LazyDetails summary="操作参数">
          <StructuredResult value={operation.payload} />
        </LazyDetails>
      )}
      {["fs.delete_batch", "cache.delete_batch", "cache.stop"].includes(
        operation.action,
      ) &&
        Array.isArray(batchTargets) && (
          <div>
            <p>
              已返回 {steps.filter((step) => step[batchKey]).length} /{" "}
              {batchTargets.length} 项结果；成功{" "}
              {steps.filter((step) => step[batchKey] && !step.failed).length}{" "}
              项，失败{" "}
              {steps.filter((step) => step[batchKey] && step.failed).length}{" "}
              项。
            </p>
            {batchTargets
              .filter((name) => !steps.some((step) => step[batchKey] === name))
              .map((name) => (
                <p key={String(name)}>
                  {String(name)}：
                  {active ? "等待结果" : "未返回结果，请核实远端状态后再操作"}
                </p>
              ))}
          </div>
        )}
      {steps.map((step, index) => (
        <section className="resource-step" key={index}>
          <p>
            步骤 {index + 1}
            {step[batchKey]
              ? ` · ${step[batchKey]} · ${step.failed ? "失败" : "成功"}`
              : ""}{" "}
            · 退出码：{step.returncode ?? "未知"}
          </p>
          {step.message && (
            <p className={step.failed ? "error" : ""}>{step.message}</p>
          )}
          {operation.action === "mount.logs" && Array.isArray(object(step.data)?.files) && (
            <div className="resource-client-log-list">
              <p className="muted">双击日志文件查看内容；点击列名排序。</p>
              <LogFileTable
                files={(object(step.data)?.files as unknown[])
                  .filter((file) => typeof file === "string" || typeof object(file)?.name === "string")
                  .map((file) => {
                    const row = object(file);
                    const name = typeof file === "string" ? file : String(row?.name);
                    return {
                      file_id: name,
                      name,
                      size: typeof row?.size === "number" ? row.size : 0,
                      mtime: typeof row?.mtime === "number" ? row.mtime : 0,
                    } satisfies RemoteFile;
                  })}
                disabled={!onOpenLog}
                onOpen={(file) => onOpenLog?.(operation, file.name)}
              />
            </div>
          )}
          {operation.action === "mount.logs" && (typeof object(step.data)?.text === "string" || typeof object(step.data)?.content === "string") && (
            <pre className="resource-output" aria-label="客户端日志内容">{String(object(step.data)?.text ?? object(step.data)?.content)}</pre>
          )}
          {step.data != null && operation.action !== "mount.logs" && (
            <QueryResult
              value={step.data}
              failed={
                abnormal || (step.returncode != null && step.returncode !== 0)
              }
            />
          )}
          {step.stderr && (
            <pre
              className="resource-output error"
              aria-label={`步骤 ${index + 1} 错误输出`}
            >
              {step.stderr}
            </pre>
          )}
          {step.stdout && (
            <LazyDetails
              summary="原始输出"
              open={operation.action === "mount.logs" || step.data == null}
            >
              <pre className="resource-output">{step.stdout}</pre>
            </LazyDetails>
          )}
        </section>
      ))}
      {operation.result && !steps.length && (
        <StructuredResult value={operation.result} />
      )}
    </article>
  );
});
