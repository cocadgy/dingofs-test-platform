import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { type Operation } from "./types";
import { OperationAuthDialog } from "./OperationAuthDialog";
const actions = { start: "启动", stop: "停止", restart: "重启" } as const;
type Scope = "all" | "role" | "service";
export function ClusterControl({
  id,
  name,
  revision,
  services,
  canOperate,
  onComplete,
}: {
  id: string;
  name: string;
  revision: number;
  services: { id: string; role: string; host: string }[];
  canOperate: boolean;
  onComplete: () => void;
}) {
  const [scope, setScope] = useState<Scope>("all");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [operation, setOperation] = useState<Operation>();
  const [description, setDescription] = useState("");
  const live = useRef(true),
    completed = useRef("");
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const accept = useCallback((op: Operation) => {
    if (live.current) setOperation(op);
  }, []);
  useEffect(() => {
    if (
      operation &&
      ["succeeded", "failed", "cancelled", "interrupted"].includes(
        operation.state,
      ) &&
      completed.current !== operation.id
    ) {
      completed.current = operation.id;
      onComplete();
    }
  }, [operation, onComplete]);
  const options =
    scope === "role"
      ? [...new Set(services.map((s) => s.role))].map((role) => ({
          value: role,
          label: role,
        }))
      : services.map((s) => ({
          value: s.id,
          label: `${s.role} · ${s.host} · ${s.id}`,
        }));
  const active =
    busy ||
    (!!operation &&
      ["pending", "running", "needs_password"].includes(operation.state));
  const valid = scope === "all" || options.some((o) => o.value === target);
  async function execute(action: keyof typeof actions) {
    if (!canOperate || active || !valid) return;
    const label =
      scope === "all"
        ? "全部服务"
        : `${scope === "role" ? "角色" : "服务"} ${options.find((o) => o.value === target)?.label}`;
    const description = `${actions[action]} · ${label}`;
    if (!window.confirm(`确认${actions[action]}集群「${name}」中的${label}？`))
      return;
    setBusy(true);
    setError("");
    setDescription(description);
    setOperation(undefined);
    try {
      accept(
        await api<Operation>(`/clusters/${id}/control`, "POST", {
          base_revision: revision,
          action,
          scope,
          target: scope === "all" ? null : target,
          confirmed: true,
        }),
      );
    } catch (e) {
      if (live.current)
        setError(
          (e as Error).message +
            "。若请求已发出，请先刷新状态核实结果，再决定是否重新操作。",
        );
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>集群管理</h2>
      {!canOperate && (
        <p className="muted">
          仅创建者或管理员可操作；采集或其他操作进行中时，请等待完成。
        </p>
      )}
      <div className="form-grid">
        <label>
          操作范围
          <select
            disabled={active || !canOperate}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as Scope);
              setTarget("");
            }}
          >
            <option value="all">全部服务</option>
            <option value="role">指定角色</option>
            <option value="service">指定服务</option>
          </select>
        </label>
        {scope !== "all" && (
          <label>
            操作目标
            <select
              disabled={active || !canOperate}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">
                请选择{scope === "role" ? "角色" : "服务"}
              </option>
              {options.map((o) => (
                <option value={o.value} key={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {scope !== "all" && !options.length && (
        <p>请先刷新集群状态以获取服务和角色列表。</p>
      )}
      <div className="actions">
        {Object.entries(actions).map(([action, label]) => (
          <button
            key={action}
            disabled={!canOperate || active || !valid}
            onClick={() => execute(action as keyof typeof actions)}
          >
            {label}
          </button>
        ))}
      </div>
      {description && <p>{description}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {operation && (
        <OperationAuthDialog operation={operation} onChange={accept} />
      )}
      {operation?.state === "succeeded" && (
        <p role="status">命令执行完成，已请求刷新集群状态。</p>
      )}
      {operation &&
        ["failed", "interrupted", "cancelled"].includes(operation.state) && (
          <p className="error">
            操作未正常完成，部分服务可能已经发生变化；取消等待不会撤销远端操作。请核实最新状态后再操作。
          </p>
        )}
      {operation?.result && (
        <details>
          <summary>操作输出</summary>
          <pre className="cluster-raw">
            {String(operation.result.stdout || "")}
            {operation.result.stderr
              ? "\n" + String(operation.result.stderr)
              : ""}
          </pre>
        </details>
      )}
    </section>
  );
}
