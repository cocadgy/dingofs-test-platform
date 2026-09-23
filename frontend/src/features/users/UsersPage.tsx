import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
type User = components["schemas"]["UserView"];
export function UsersPage({
  currentId,
  onSessionRevoked,
  onDirty,
}: {
  currentId: string;
  onSessionRevoked: () => void;
  onDirty: (v: boolean) => void;
}) {
  const [items, setItems] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    onDirty(editing && (!!username || !!email || !!password));
    return () => onDirty(false);
  }, [editing, username, email, password, onDirty]);
  useEffect(() => {
    let live = true;
    api<{ items: User[]; total: number }>(
      `/users?q=${encodeURIComponent(query)}&limit=20&offset=${offset}`,
    )
      .then((r) => {
        if (live) {
          setItems(r.items);
          setTotal(r.total);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [query, offset, refresh]);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const body: components["schemas"]["NewUser"] = {
        username,
        email,
        password,
        role,
      };
      await api("/users", "POST", body);
      setEditing(false);
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("member");
      setNotice("用户已创建");
      setOffset(0);
      setQuery("");
      setRefresh((x) => x + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function action(user: User, kind: "status" | "reset" | "delete") {
    const actionText =
      kind === "reset"
        ? `将「${user.username}」的密码重置为 123456，并使其登录会话失效？`
        : kind === "delete"
          ? `永久删除用户「${user.username}」？该用户将无法登录，历史操作记录保留。`
          : `${user.disabled ? "启用" : "禁用"}用户「${user.username}」？`;
    if (!confirm(actionText)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const path = "/users/" + user.id;
      if (kind === "reset")
        await api(path + "/reset-password", "POST", {
          base_revision: user.revision,
        });
      else if (kind === "delete")
        await api(path + `?base_revision=${user.revision}`, "DELETE");
      else
        await api(path, "PATCH", {
          base_revision: user.revision,
          disabled: !user.disabled,
        });
      if (user.id === currentId && (kind !== "status" || !user.disabled)) {
        onSessionRevoked();
        return;
      }
      setNotice(
        kind === "reset"
          ? `「${user.username}」的密码已重置为 123456`
          : kind === "delete"
            ? "用户已删除"
            : user.disabled
              ? "用户已启用"
              : "用户已禁用",
      );
      setRefresh((x) => x + 1);
    } catch (e) {
      setError((e as Error).message);
      setRefresh((x) => x + 1);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / USERS</p>
          <h1>用户管理</h1>
          <p className="muted">管理平台账号、邮箱和访问状态。</p>
        </div>
        <button className="primary" onClick={() => setEditing(true)}>
          添加用户
        </button>
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      {editing && (
        <form className="panel detail user-create" onSubmit={create}>
          <h2>添加用户</h2>
          <div className="form-grid">
            <label>
              用户名
              <input
                required
                maxLength={80}
                pattern="[A-Za-z0-9_.\-]+"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label>
              邮箱
              <input
                type="email"
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              初始密码
              <input
                type="password"
                required
                minLength={6}
                maxLength={1024}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              角色
              <select
                aria-label="角色"
                value={role}
                onChange={(e) => setRole(e.target.value as "member" | "admin")}
              >
                <option value="member">普通成员</option>
                <option value="admin">管理员</option>
              </select>
            </label>
          </div>
          <p className="muted">
            初始密码至少 6 位。重置密码功能固定重置为 123456。
          </p>
          <div className="actions">
            <button className="primary" disabled={busy}>
              创建用户
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (
                  (username || email || password) &&
                  !confirm("放弃未保存的用户信息？")
                )
                  return;
                setEditing(false);
                setUsername("");
                setEmail("");
                setPassword("");
              }}
            >
              取消
            </button>
          </div>
        </form>
      )}
      <section className="panel">
        <label className="search">
          搜索用户名
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <div className="user-table">
          <table>
            <thead>
              <tr>
                <th>用户名</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.username}
                    {u.id === currentId ? "（当前用户）" : ""}
                  </td>
                  <td>{u.email || "待补填"}</td>
                  <td>{u.role === "admin" ? "管理员" : "普通成员"}</td>
                  <td>{u.disabled ? "已禁用" : "已启用"}</td>
                  <td>
                    <div className="user-actions">
                      <button
                        disabled={busy}
                        onClick={() => action(u, "status")}
                      >
                        {u.disabled ? "启用" : "禁用"}
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => action(u, "reset")}
                      >
                        重置密码
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => action(u, "delete")}
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!items.length && <p className="empty">没有匹配的用户</p>}
        </div>
        <div className="pagination">
          <button
            disabled={!offset}
            onClick={() => setOffset((x) => Math.max(0, x - 20))}
          >
            上一页
          </button>
          <span>共 {total} 位用户</span>
          <button
            disabled={offset + 20 >= total}
            onClick={() => setOffset((x) => x + 20)}
          >
            下一页
          </button>
        </div>
      </section>
    </>
  );
}
