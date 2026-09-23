import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { type Operation, statusNames } from "./types";
export function OperationAuthDialog({
  operation,
  onChange,
}: {
  operation: Operation;
  onChange: (op: Operation) => void;
}) {
  const [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    setPassword("");
    setError("");
  }, [operation.id, operation.challenge]);
  useEffect(() => {
    if (!["pending", "running"].includes(operation.state)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Operation>(
          "/cluster-operations/" + operation.id,
        );
        if (active) {
          onChange(next);
          if (["pending", "running"].includes(next.state))
            timer = setTimeout(poll, 1200);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    timer = setTimeout(poll, 400);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [operation.id, operation.state, onChange]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const secret = password;
    setPassword("");
    try {
      const next = await api<Operation>(
        `/cluster-operations/${operation.id}/authenticate`,
        "POST",
        { challenge: operation.challenge, password: secret },
      );
      if (live.current) onChange(next);
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  async function cancel() {
    setPassword("");
    setBusy(true);
    try {
      const next = await api<Operation>(
        `/cluster-operations/${operation.id}/cancel`,
        "POST",
      );
      if (live.current) onChange(next);
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  if (operation.state === "succeeded") return null;
  return (
    <section className="cluster-operation" aria-label="操作进度">
      <p role="status">
        {statusNames[operation.state] || operation.state} {operation.message}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {operation.state === "needs_password" && (
        <form onSubmit={submit}>
          <h3>用户切换认证</h3>
          <p>
            执行机器：{operation.machine_name} · SSH 用户：{operation.ssh_user}{" "}
            · 目标用户：{operation.target_user}
          </p>
          <p>
            <strong>需要验证账号：{operation.auth_account}</strong>
          </p>
          <p className="muted">
            密码仅用于本次操作，不会保存。这里不是网站登录密码。
          </p>
          <label>
            认证密码
            <input
              type="password"
              autoComplete="off"
              required
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
        <p>
          请管理员打开
          <a
            href={`#/machines/${operation.machine_id}`}
            onClick={(e) => {
              e.preventDefault();
              window.dispatchEvent(
                new CustomEvent("platform-navigate", {
                  detail: { kind: "machines", id: operation.machine_id },
                }),
              );
            }}
          >
            机器详情
          </a>
          ，更新机器信息并核验 SSH 指纹后重新发现。
        </p>
      )}
      {["pending", "running", "needs_password", "needs_trust"].includes(
        operation.state,
      ) && (
        <button onClick={cancel} disabled={busy}>
          取消本次操作
        </button>
      )}
    </section>
  );
}
