import { useEffect, useState } from "react";
import type { RemoteController } from "./useRemoteSession";
const states: Record<string, string> = {
  pending: "等待连接",
  connecting: "正在连接",
  needs_password: "等待临时认证",
  needs_trust: "等待主机指纹确认",
  ready: "准备就绪",
  running: "连接中",
  succeeded: "已完成",
  failed: "失败",
  closed: "已断开",
  interrupted: "已中断",
};
export function RemoteSessionStatus({ remote }: { remote: RemoteController }) {
  const [password, setPassword] = useState("");
  const row = remote.session;
  useEffect(() => {
    setPassword("");
  }, [row?.id, row?.challenge, row?.state]);
  return (
    <div className="remote-status">
      <p role="status">
        {remote.busy ? "正在处理…" : row ? states[row.state] : "尚未连接"}
        {row?.target_user ? ` · 远程用户 ${row.target_user}` : ""}
      </p>
      {remote.error && (
        <p role="alert" className="error">
          {remote.error}
        </p>
      )}
      {row?.state === "needs_password" && (
        <form
          key={row.challenge}
          onSubmit={(e) => {
            e.preventDefault();
            const value = password;
            setPassword("");
            void remote.authenticate(value);
          }}
        >
          <p>
            请为账号 <strong>{row.auth_account || row.target_user}</strong>{" "}
            提供本次连接需要的临时密码。
          </p>
          <label>
            临时认证密码
            <input
              type="password"
              autoComplete="off"
              value={password}
              required
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button disabled={remote.busy}>提交临时密码</button>
          <button
            type="button"
            onClick={() => {
              setPassword("");
              remote.close();
            }}
          >
            取消连接
          </button>
        </form>
      )}
      {row?.state === "needs_trust" && (
        <p>
          请先到{" "}
          <a href={`#/machines/${encodeURIComponent(row.machine_id)}`}>
            机器资源详情
          </a>{" "}
          刷新并核对主机指纹，确认后返回此页面重新连接。
        </p>
      )}
    </div>
  );
}
