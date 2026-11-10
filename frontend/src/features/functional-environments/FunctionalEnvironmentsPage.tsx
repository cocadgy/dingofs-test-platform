import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { LogLoading } from "../remote/LogLoading";
import { Choice, Draft, EnvironmentEditor } from "./EnvironmentEditor";
import "./functional-environments.css";
type Profile = {
  id: string;
  name: string;
  source_kind: "predefined" | "custom";
  source_file: string | null;
  revision: number;
  enabled: boolean;
  validation: string;
  cluster_id: string | null;
  machine_id: string | null;
  storage_profile_id: string | null;
  settings: Record<string, unknown>;
  display: {
    client_count?: number;
    cache_count?: number;
    storage_type?: string;
    client_hosts?: string[];
    validated_at?: string;
  };
  can_manage: boolean;
  updated_at: string;
};
const blank: Draft = {
  name: "",
  cluster_id: "",
  machine_id: "",
  storage_profile_id: "",
  mount_root: "/tmp/dingofs-functional",
  fs_prefix: "platform-test",
  binaries: {},
  clients: [],
  remote_caches: [],
  enabled: true,
};
const base = "#/configuration/test-environments";
const statusLabels: Record<string, string> = {
  template: "基础模板",
  needs_completion: "需补全",
  ready: "验证通过",
  failed: "验证失败",
  needs_validation: "待验证",
  source_only: "预置可用",
  source_missing: "源文件缺失",
};
function counts(row: Profile) {
  const s = row.settings || {};
  return `${row.display.client_count ?? (s.clients as Draft["clients"])?.reduce((n, c) => n + c.client_count, 0) ?? 1} 客户端 · ${row.display.cache_count ?? (s.remote_caches as Draft["remote_caches"])?.reduce((n, c) => n + c.remote_cache_count, 0) ?? 0} 缓存成员`;
}
function toDraft(row: Profile, settings = row.settings || {}): Draft {
  return {
    id: row.source_kind === "custom" ? row.id : undefined,
    sourceId: row.source_kind === "predefined" ? row.id : undefined,
    revision: row.revision,
    name: row.source_kind === "predefined" ? row.name + "-copy" : row.name,
    cluster_id: row.cluster_id || "",
    machine_id: row.machine_id || "",
    storage_profile_id: row.storage_profile_id || "",
    mount_root: String(settings.mount_root || blank.mount_root),
    fs_prefix: String(settings.fs_prefix || blank.fs_prefix),
    binaries: (settings.binaries as Draft["binaries"]) || {},
    clients: (settings.clients as Draft["clients"]) || [],
    remote_caches: (settings.remote_caches as Draft["remote_caches"]) || [],
    enabled: row.source_kind === "predefined" ? true : row.enabled,
  };
}
export function FunctionalEnvironmentsPage({
  onDirty,
}: {
  onDirty: (dirty: boolean) => void;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [clusters, setClusters] = useState<Choice[]>([]);
  const [machines, setMachines] = useState<Choice[]>([]);
  const [storage, setStorage] = useState<(Choice & { enabled: boolean })[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [checks, setChecks] = useState<
    { name: string; success: boolean; message?: string }[]
  >([]);
  const [path, setPath] = useState(window.location.hash);
  const [loaded, setLoaded] = useState(false);
  const opening = useRef("");
  useEffect(() => {
    const sync = () => setPath(window.location.hash);
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  function navigate(next = "") {
    const hash = base + (next ? "/" + next : "");
    window.location.hash = hash;
    setPath(hash);
  }
  async function refresh() {
    try {
      const [p, o, m, s] = await Promise.all([
        api<Profile[]>("/functional/environments"),
        api<{ clusters: Choice[] }>("/functional/options"),
        api<{ items: Choice[] }>("/machines?limit=200"),
        api<(Choice & { enabled: boolean })[]>("/storage-profiles"),
      ]);
      setProfiles(p);
      setClusters(o.clusters);
      setMachines(m.items);
      setStorage(s);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (!loaded) return;
    const suffix = path.slice(base.length);
    if (!suffix) {
      setDraft(null);
      opening.current = "";
      onDirty(false);
      return;
    }
    if (suffix === "/new") {
      if (opening.current !== path) {
        setDraft({ ...blank });
        opening.current = path;
        onDirty(true);
      }
      return;
    }
    const id = decodeURIComponent(suffix.split("/")[2] || "");
    const value = profiles.find((p) => p.id === id);
    if (!value) {
      setError("测试环境不存在，请返回列表");
      return;
    }
    if (opening.current === path) return;
    opening.current = path;
    let live = true;
    if (value.source_kind === "predefined") {
      setBusy(true);
      api<{ settings: Record<string, unknown>; warnings: string[] }>(
        `/functional/environments/${value.id}/copy-settings`,
      )
        .then((result) => {
          if (live) {
            setDraft(toDraft(value, result.settings));
            setNotice(result.warnings.join(" "));
            onDirty(true);
          }
        })
        .catch((e) => {
          if (live) setError((e as Error).message);
        })
        .finally(() => {
          if (live) setBusy(false);
        });
    } else {
      setDraft(toDraft(value));
      onDirty(true);
    }
    return () => {
      live = false;
    };
  }, [path, loaded, profiles]);
  function change(patch: Partial<Draft>) {
    if (!busy) {
      setDraft((d) => (d ? { ...d, ...patch } : d));
      onDirty(true);
    }
  }
  function close() {
    if (busy) return;
    setDraft(null);
    onDirty(false);
    opening.current = "";
    navigate();
  }
  async function save() {
    if (!draft || busy) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        name: draft.name.trim(),
        cluster_id: draft.cluster_id,
        machine_id: draft.machine_id,
        storage_profile_id: draft.storage_profile_id || null,
        settings: {
          mount_root: draft.mount_root,
          fs_prefix: draft.fs_prefix,
          client_count: 1,
          clients: draft.clients.length
            ? draft.clients
            : [
                {
                  machine_id: draft.machine_id,
                  client_count: 1,
                  mount_path: draft.mount_root,
                  fs_name: draft.fs_prefix,
                  client_conf: {},
                },
              ],
          remote_caches: draft.remote_caches,
          binaries: Object.fromEntries(
            Object.entries(draft.binaries)
              .filter(([, value]) => value.trim())
              .map(([key, value]) => [key, value.trim()]),
          ),
        },
        enabled: draft.enabled,
      };
      if (draft.id)
        await api(`/functional/environments/${draft.id}`, "PUT", {
          ...body,
          revision: draft.revision,
        });
      else if (draft.sourceId)
        await api(
          `/functional/environments/${draft.sourceId}/copy`,
          "POST",
          body,
        );
      else await api("/functional/environments", "POST", body);
      setDraft(null);
      onDirty(false);
      opening.current = "";
      navigate();
      setNotice("测试环境已保存");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function preflight(id: string) {
    setBusy(true);
    setError("");
    setChecks([]);
    try {
      const result = await api<{
        success: boolean;
        items: { name: string; success: boolean; message?: string }[];
      }>(`/functional/environments/${id}/preflight`, "POST");
      setChecks(result.items);
      setNotice(
        result.success ? "环境验证通过" : "环境验证失败，请查看检查结果",
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function sync() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ total: number }>(
        "/functional/environments/sync-predefined",
        "POST",
      );
      setNotice(`已同步 ${result.total} 个预置环境`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const rows = profiles.filter((p) =>
    `${p.name} ${clusters.find((c) => c.id === p.cluster_id)?.name || ""}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const editing = path.startsWith(base + "/");
  return (
    <section className="functional-environments">
      {busy && <LogLoading label="正在处理测试环境…" popup />}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="functional-environments-notice">
          {notice}
        </p>
      )}
      {checks.length > 0 && (
        <details>
          <summary>查看环境检查结果</summary>
          <ul>
            {checks.map((c, i) => (
              <li key={i}>
                {c.success ? "✓ 通过" : "✗ 失败"} · {c.name}
                {c.message ? `：${c.message}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
      {editing ? (
        <>
          <button disabled={busy} onClick={close}>
            ← 返回环境列表
          </button>
          {draft && (
            <EnvironmentEditor
              draft={draft}
              change={change}
              close={close}
              save={save}
              busy={busy}
              clusters={clusters}
              machines={machines}
              storage={storage}
            />
          )}
        </>
      ) : (
        <>
          <div className="functional-environments-toolbar">
            <input
              type="search"
              aria-label="搜索测试环境"
              placeholder="搜索环境名称或集群"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              disabled={busy || !loaded}
              onClick={() => {
                setNotice("");
                navigate("new");
              }}
            >
              新建测试环境
            </button>
            <button disabled={busy} onClick={() => void sync()}>
              同步预置环境
            </button>
          </div>
          <p>
            预置环境可复制参数后重新绑定机器和存储。保存配置不会创建文件系统或挂载客户端。
          </p>
          <div className="functional-environments-table">
            <table>
              <thead>
                <tr>
                  <th>名称 / 来源</th>
                  <th>集群</th>
                  <th>状态</th>
                  <th>实例数量</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                      <small>
                        {row.source_kind === "predefined"
                          ? `预置 · ${row.source_file}`
                          : "自建"}
                      </small>
                    </td>
                    <td>
                      {clusters.find((c) => c.id === row.cluster_id)?.name ||
                        "预置集群"}
                      <small>
                        {machines.find((m) => m.id === row.machine_id)?.name ||
                          row.display.client_hosts?.join("、") ||
                          "—"}
                      </small>
                    </td>
                    <td>
                      <span
                        className={`environment-state environment-${row.enabled ? row.validation : "disabled"}`}
                      >
                        {row.validation === "template"
                          ? "基础模板"
                          : !row.enabled
                            ? "已停用"
                            : statusLabels[row.validation] || "待验证"}
                      </span>
                      {row.display.validated_at && (
                        <small>
                          {new Date(row.display.validated_at).toLocaleString()}
                        </small>
                      )}
                    </td>
                    <td>{counts(row)}</td>
                    <td>
                      {row.source_kind === "predefined" ? (
                        <button
                          disabled={busy}
                          onClick={() => {
                            setError("");
                            navigate(`copy/${row.id}`);
                          }}
                        >
                          复制为自建
                        </button>
                      ) : row.can_manage ? (
                        <div className="functional-environments-row-actions">
                          <button
                            disabled={busy}
                            onClick={() => {
                              setNotice("");
                              navigate(`edit/${row.id}`);
                            }}
                          >
                            编辑
                          </button>
                          <button
                            disabled={busy || !row.enabled}
                            onClick={() => void preflight(row.id)}
                          >
                            验证
                          </button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <p>{loaded ? "没有匹配环境" : "正在读取环境…"}</p>}
          </div>
        </>
      )}
    </section>
  );
}
