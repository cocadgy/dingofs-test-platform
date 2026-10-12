import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { CacheParameterEditor } from "../cache-profiles/CacheParameterEditor";
import type { CacheCatalog, CacheProfile } from "../cache-profiles/types";
import "../cache-profiles/cache-profiles.css";

type Draft = Pick<
  CacheProfile,
  "name" | "description" | "enabled" | "parameters"
>;
export function MountProfilesPage({
  onDirty,
}: {
  onDirty: (dirty: boolean) => void;
}) {
  const [items, setItems] = useState<CacheProfile[]>([]);
  const [catalog, setCatalog] = useState<CacheCatalog>();
  const [draft, setDraft] = useState<Draft>();
  const [editing, setEditing] = useState<CacheProfile>();
  const [baseline, setBaseline] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [refresh, setRefresh] = useState(0);
  const dirty = !!draft && JSON.stringify(draft) !== baseline;
  const editable = !editing || editing.can_manage;
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    Promise.all([
      api<CacheProfile[]>("/mount-profiles"),
      api<CacheCatalog>("/mount-profiles/catalog"),
    ])
      .then(([rows, data]) => {
        if (alive) {
          setItems(rows);
          setCatalog(data);
        }
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [refresh]);
  function open(profile?: CacheProfile, copy = false) {
    if (dirty && !confirm("有未保存修改，确定切换配置？")) return;
    const next: Draft = {
      name: profile ? (copy ? `${profile.name} 副本` : profile.name) : "",
      description: profile?.description || "",
      enabled: profile?.enabled ?? true,
      parameters: { ...profile?.parameters },
    };
    setDraft(next);
    setBaseline(JSON.stringify(next));
    setEditing(copy ? undefined : profile);
    setError("");
    setNotice("");
  }
  async function save() {
    if (!draft || busy || !editable) return;
    setBusy(true);
    setError("");
    try {
      const row = await api<CacheProfile>(
        editing ? `/mount-profiles/${editing.id}` : "/mount-profiles",
        editing ? "PUT" : "POST",
        { ...draft, ...(editing ? { revision: editing.revision } : {}) },
      );
      setItems((prev) =>
        [...prev.filter((p) => p.id !== row.id), row].sort((a, b) =>
          a.name.localeCompare(b.name),
        ),
      );
      setEditing(row);
      setBaseline(JSON.stringify(draft));
      setNotice("挂载配置已保存。已有挂载和已提交任务不受影响。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(row: CacheProfile) {
    if (
      busy ||
      !row.can_manage ||
      !confirm(`删除挂载配置“${row.name}”？已有挂载不受影响。`)
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api(`/mount-profiles/${row.id}?revision=${row.revision}`, "DELETE");
      setItems((prev) => prev.filter((p) => p.id !== row.id));
      if (editing?.id === row.id) {
        setDraft(undefined);
        setEditing(undefined);
      }
      setNotice("配置已删除。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="cache-profiles-page">
      <div className="page-header">
        <div>
          <p className="eyebrow">CACHE PROFILES</p>
          <h1>挂载配置</h1>
          <p>集中管理启动参数；创建时选择配置，还可以修改本次参数。</p>
        </div>
        <button
          className="primary"
          disabled={busy || !catalog}
          onClick={() => open()}
        >
          新建挂载配置
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className="cache-profile-toolbar">
        <label>
          搜索配置
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="名称或说明"
          />
        </label>
        <button
          disabled={busy || loading}
          onClick={() => setRefresh((v) => v + 1)}
        >
          刷新配置列表
        </button>
      </div>
      {loading && <p>正在读取挂载配置…</p>}
      <div className="cache-profile-list">
        <table>
          <thead>
            <tr>
              <th>配置名称</th>
              <th>说明</th>
              <th>已配置参数</th>
              <th>状态</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items
              .filter((p) =>
                `${p.name} ${p.description}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
              )
              .map((row) => (
                <tr key={row.id}>
                  <td>
                    <button
                      className="link-button"
                      disabled={busy}
                      onClick={() => open(row)}
                    >
                      {row.name}
                    </button>
                  </td>
                  <td>{row.description || "—"}</td>
                  <td>{Object.keys(row.parameters).length}</td>
                  <td>{row.enabled ? "启用" : "停用"}</td>
                  <td>{new Date(row.updated_at).toLocaleString()}</td>
                  <td>
                    <button disabled={busy} onClick={() => open(row, true)}>
                      复制
                    </button>
                    {row.can_manage && (
                      <button disabled={busy} onClick={() => void remove(row)}>
                        删除
                      </button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
        {!loading && !items.length && (
          <p>尚无挂载配置，可新建模板或在挂载文件系统时直接设置参数。</p>
        )}
      </div>
      {draft && catalog && (
        <form
          className="cache-profile-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <h2>{editing ? (editable ? "编辑配置" : "查看配置") : "新建配置"}</h2>
          {!editable && (
            <p className="muted">
              只读配置。可复制为自己的模板；挂载文件系统时仍可临时修改。
            </p>
          )}
          <fieldset
            disabled={busy || !editable}
            className="cache-profile-basics"
          >
            <label>
              配置名称
              <input
                required
                maxLength={120}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
            <label>
              说明
              <input
                maxLength={2000}
                value={draft.description}
                onChange={(e) =>
                  setDraft({ ...draft, description: e.target.value })
                }
              />
            </label>
            <label className="cache-inline">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(e) =>
                  setDraft({ ...draft, enabled: e.target.checked })
                }
              />
              启用配置
            </label>
          </fieldset>
          <CacheParameterEditor tool="dingo-client"
            catalog={catalog}
            values={draft.parameters}
            disabled={busy || !editable}
            onChange={(parameters) => setDraft({ ...draft, parameters })}
          />
          <div className="cache-profile-actions">
            {editable && (
              <button className="primary" disabled={busy}>
                {busy ? "正在保存…" : "保存配置"}
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (!dirty || confirm("放弃未保存修改？")) {
                  setDraft(undefined);
                  setEditing(undefined);
                }
              }}
            >
              关闭
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
