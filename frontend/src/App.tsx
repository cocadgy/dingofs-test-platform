import {ConfigurationPage} from "./features/configuration/ConfigurationPage";
import { CacheProfilesPage } from "./features/cache-profiles/CacheProfilesPage";
import { BadouMascot } from "./components/BadouMascot";
import { StorageProfilesPage } from "./features/storage/StorageProfilesPage";
import { useEffect, useState } from "react";
import { api, setCsrf } from "./api/client";
import { InventoryPage, sections } from "./features/inventory/InventoryPage";
import { ClusterPage } from "./features/clusters/ClusterPage";
import { MachinePage } from "./features/inventory/MachinePage";
import { UsersPage } from "./features/users/UsersPage";
import { ProfilePage } from "./features/users/ProfilePage";
import { LogPage } from "./features/remote/LogPage";
import { LogSearchResultPage } from "./features/remote/LogSearchResultPage";
import { MountLogPage, mountLogRoute } from "./features/resources/MountLogPage";
import { TerminalPage } from "./features/remote/TerminalPage";
import {
  ClusterResourcesPage,
  resourceRoute,
} from "./features/resources/ClusterResourcesPage";
import { remoteRoute } from "./features/remote/routes";
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
  const [hash, setHash] = useState(window.location.hash);
  const remote = remoteRoute(hash);
  const resourceCluster = resourceRoute(hash);
  const mountLog = mountLogRoute(hash);
  useEffect(() => {
    const sync = () =>
      queueMicrotask(() => {
        setHash(window.location.hash);
        if (user?.email) {
          if (window.location.hash.startsWith("#/clusters"))
            setKind("clusters");
          else if (/^#\/(configuration|cache-profiles|mount-profiles|storage)(\/|$)/.test(window.location.hash)) setKind("configuration");
          else if (window.location.hash.startsWith("#/machines"))
            setKind("machines");
        }
      });
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [user?.email]);
  function session(u: User) {
    setUser(u);
    setHash(window.location.hash);
    setKind(
      u.email
        ? window.location.hash.startsWith("#/clusters")
          ? "clusters"
          : /^#\/(configuration|cache-profiles|mount-profiles|storage)(\/|$)/.test(window.location.hash)
            ? "configuration"
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
      setHash(window.location.hash);
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
          <BadouMascot size="large" />
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
          <BadouMascot />
          <div>
            DingoFS<strong>测试平台</strong>
          </div>
        </div>
        <p className="nav-label">工作空间</p>
        <nav>
          {Object.entries({
            ...sections,
            configuration: "配置管理",
            ...(user.role === "admin" ? { users: "用户管理" } : {}),
            profile: "个人设置",
          }).map(([key, label]) => (
            <button
              key={key}
              aria-current={kind === key ? "page" : undefined}
              onClick={() => {
                if (key === kind) {
                  if (
                    [
                      "machines",
                      "clusters",
                      "storage",
                      "cache-profiles",
                      "configuration",
                    ].includes(key)
                  )
                    window.location.hash = "#/" + key;
                  return;
                }
                if (!dirty || confirm("有未保存修改，确定离开？")) {
                  setDirty(false);
                  window.history.replaceState(
                    null,
                    "",
                    [
                      "machines",
                      "clusters",
                      "storage",
                      "cache-profiles",
                      "configuration",
                    ].includes(key)
                      ? "#/" + key
                      : window.location.pathname + window.location.search,
                  );
                  setHash(window.location.hash);
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
            (["machines", "clusters", "storage", "cache-profiles", "configuration"].includes(
              kind,
            )
              ? " machines-content"
              : "")
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
          ) : kind === "configuration" ? (
            <ConfigurationPage onDirty={setDirty} />
          ) : kind === "cache-profiles" ? (
            <CacheProfilesPage onDirty={setDirty} />
          ) : kind === "storage" ? (
            <StorageProfilesPage onDirty={setDirty} />
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
          ) : kind === "clusters" && remote ? (
            remote.kind === "logs" && remote.searchKeyword !== undefined && remote.searchFile !== undefined ? (
              <LogSearchResultPage key={hash} clusterId={remote.clusterId} serviceId={remote.targetId} fileName={remote.searchFile} keyword={remote.searchKeyword} caseSensitive={!!remote.searchCaseSensitive} backUrl={`#/clusters/${encodeURIComponent(remote.clusterId)}/logs/${encodeURIComponent(remote.targetId)}`} />
            ) : remote.kind === "logs" ? (
              <LogPage
                key={hash}
                clusterId={remote.clusterId}
                serviceId={remote.targetId}
                fileName={remote.fileName}
              />
            ) : (
              <TerminalPage
                key={hash}
                clusterId={remote.clusterId}
                machineId={remote.targetId}
                admin={user.role === "admin"}
              />
            )
          ) : kind === "clusters" && mountLog?.searchKeyword !== undefined && mountLog.searchFile !== undefined ? (
            <LogSearchResultPage key={hash} clusterId={mountLog.clusterId} serviceId={`mount:${mountLog.resourceId}`} fileName={mountLog.searchFile} keyword={mountLog.searchKeyword} caseSensitive={!!mountLog.searchCaseSensitive} backUrl={`#/clusters/${encodeURIComponent(mountLog.clusterId)}/resources/mounts/${encodeURIComponent(mountLog.resourceId)}/logs`} />
          ) : kind === "clusters" && mountLog ? (
            <MountLogPage key={hash} clusterId={mountLog.clusterId} resourceId={mountLog.resourceId} fileName={mountLog.fileName} />
          ) : kind === "clusters" && resourceCluster ? (
            <ClusterResourcesPage
              key={resourceCluster}
              id={resourceCluster}
              admin={user.role === "admin"}
              userId={user.id}
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
