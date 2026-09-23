import { useEffect, useState } from "react";
import { api, setCsrf } from "./api/client";
import { InventoryPage, sections } from "./features/inventory/InventoryPage";
import { ClusterPage } from "./features/clusters/ClusterPage";
import { MachinePage } from "./features/inventory/MachinePage";
import { UsersPage } from "./features/users/UsersPage";
import { ProfilePage } from "./features/users/ProfilePage";
type User = {
  id: string;
  username: string;
  email: string | null;
  role: string;
  csrf_token: string;
};
export function App() {
  const [user, setUser] = useState<User>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [kind, setKind] = useState("machines");
  function session(u: User) {
    setUser(u);
    setKind(
      u.email
        ? window.location.hash.startsWith("#/clusters")
          ? "clusters"
          : "machines"
        : "profile",
    );
    setCsrf(u.csrf_token);
    if (!u.email) setKind("profile");
  }
  useEffect(() => {
    api<User>("/auth/me")
      .then(session)
      .catch(() => {})
      .finally(() => setLoading(false));
    const expired = () => {
      setUser(undefined);
      setCsrf("");
      setError("会话已过期，请重新登录");
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  useEffect(() => {
    const before = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, [dirty]);
  useEffect(() => {
    const navigate = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.kind !== "machines" || typeof detail.id !== "string") return;
      if (dirty && !confirm("有未保存修改，确定离开？")) return;
      setDirty(false);
      window.history.pushState(
        null,
        "",
        "#/machines/" + encodeURIComponent(detail.id),
      );
      setKind("machines");
    };
    window.addEventListener("platform-navigate", navigate);
    return () => window.removeEventListener("platform-navigate", navigate);
  }, [dirty]);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      session(await api<User>("/auth/login", "POST", { username, password }));
      setPassword("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    if (dirty && !confirm("有未保存修改，确定退出？")) return;
    try {
      await api("/auth/logout", "POST");
      setUser(undefined);
      setCsrf("");
      setDirty(false);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (loading) return <div className="loading">正在连接测试平台…</div>;
  if (!user)
    return (
      <main className="login">
        <div className="login-brand">
          <span className="logo">D</span>
          <p className="eyebrow">DINGOFS / TEST PLATFORM</p>
          <h1>
            让每一次测试
            <br />
            都有据可循。
          </h1>
          <p>统一管理机器、集群与测试环境。</p>
          <span className="badge">第一阶段 · 资源与配置管理</span>
        </div>
        <form onSubmit={login}>
          <h2>登录测试平台</h2>
          <p className="muted">使用管理员创建的团队账号</p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <label>
            用户名
            <input
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "正在登录…" : "登录"}
          </button>
        </form>
      </main>
    );
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <span className="logo">D</span>
          <div>
            DingoFS<strong>测试平台</strong>
          </div>
        </div>
        <p className="nav-label">工作空间</p>
        <nav>
          {Object.entries({
            ...sections,
            ...(user.role === "admin" ? { users: "用户管理" } : {}),
            profile: "个人设置",
          }).map(([key, label]) => (
            <button
              key={key}
              aria-current={kind === key ? "page" : undefined}
              onClick={() => {
                if (key === kind) {
                  if (["machines", "clusters"].includes(key))
                    window.location.hash = "#/" + key;
                  return;
                }
                if (!dirty || confirm("有未保存修改，确定离开？")) {
                  setDirty(false);
                  window.history.replaceState(
                    null,
                    "",
                    ["machines", "clusters"].includes(key)
                      ? "#/" + key
                      : window.location.pathname + window.location.search,
                  );
                  setKind(key);
                }
              }}
            >
              <span>{label}</span>
              <span>›</span>
            </button>
          ))}
        </nav>
        <div className="roadmap">
          <strong>第一阶段</strong>
          <p>资源登记与配置管理</p>
          <small>测试执行、报告和集群运维将在后续阶段开放。</small>
        </div>
        <div className="account">
          <strong>{user.username}</strong>
          <span>{user.role === "admin" ? "管理员" : "普通成员"}</span>
          <button onClick={logout}>退出登录</button>
        </div>
      </aside>
      <main className="workspace">
        <div className="topbar">
          <span>团队测试工作台</span>
          <span className="badge">配置管理</span>
        </div>
        <div
          className={
            "content" +
            (["machines", "clusters"].includes(kind) ? " machines-content" : "")
          }
        >
          {kind === "users" && user.role === "admin" ? (
            <UsersPage
              currentId={user.id}
              onDirty={setDirty}
              onSessionRevoked={() => {
                setUser(undefined);
                setCsrf("");
                setDirty(false);
                setKind("machines");
                setError("账号状态或密码已变更，请重新登录");
              }}
            />
          ) : kind === "profile" ? (
            <ProfilePage
              email={user.email}
              onDirty={setDirty}
              onEmailSaved={(email) => setUser({ ...user, email })}
              onPasswordChanged={() => {
                setUser(undefined);
                setCsrf("");
                setDirty(false);
                setKind("machines");
                setError("密码已修改，请使用新密码登录");
              }}
            />
          ) : kind === "clusters" ? (
            <ClusterPage
              userId={user.id}
              admin={user.role === "admin"}
              onDirty={setDirty}
            />
          ) : kind === "machines" ? (
            <MachinePage
              userId={user.id}
              admin={user.role === "admin"}
              onDirty={setDirty}
            />
          ) : (
            <InventoryPage
              key={kind}
              kind={kind}
              admin={user.role === "admin"}
              onDirty={setDirty}
            />
          )}
        </div>
      </main>
    </div>
  );
}
