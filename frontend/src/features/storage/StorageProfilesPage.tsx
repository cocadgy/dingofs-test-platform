import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { StorageProfile, StorageType } from "./types";
import "./storage.css";

type ProfileDraft = Pick<
  StorageProfile,
  "name" | "storage_type" | "description" | "enabled" | "parameters"
>;
type StorageField = {
  key: string;
  label: string;
  placeholder: string;
  secret?: boolean;
};
const fields: Record<StorageType, StorageField[]> = {
  s3: [
    {
      key: "s3_endpoint",
      label: "Endpoint",
      placeholder: "https://s3.example.com",
    },
    { key: "s3_bucketname", label: "Bucket", placeholder: "dingofs-data" },
    {
      key: "s3_ak",
      label: "Access Key",
      placeholder: "输入访问密钥",
      secret: true,
    },
    {
      key: "s3_sk",
      label: "Secret Key",
      placeholder: "输入密钥",
      secret: true,
    },
  ],
  rados: [
    { key: "rados_username", label: "Username", placeholder: "client.admin" },
    {
      key: "rados_key",
      label: "Key",
      placeholder: "输入 RADOS 密钥",
      secret: true,
    },
    {
      key: "rados_mon",
      label: "Monitors",
      placeholder: "10.0.0.1:6789,10.0.0.2:6789",
    },
    { key: "rados_poolname", label: "Pool", placeholder: "dingofs-data" },
    { key: "rados_clustername", label: "Cluster Name", placeholder: "ceph" },
  ],
};
function blankParameters(type: StorageType) {
  return Object.fromEntries(fields[type].map((field) => [field.key, ""]));
}
function makeDraft(profile?: StorageProfile): ProfileDraft {
  const type = profile?.storage_type || "s3";
  return {
    name: profile?.name || "",
    storage_type: type,
    description: profile?.description || "",
    enabled: profile?.enabled ?? true,
    parameters: Object.fromEntries(
      fields[type].map((field) => [
        field.key,
        field.secret ? "" : profile?.parameters[field.key] || "",
      ]),
    ),
  };
}
function profilePath(profile: StorageProfile) {
  return `/storage-profiles/${encodeURIComponent(profile.id)}`;
}
function updatedTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { hour12: false });
}

export function StorageProfilesPage({
  onDirty,
}: {
  onDirty: (value: boolean) => void;
}) {
  const [items, setItems] = useState<StorageProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<StorageProfile>();
  const [draft, setDraft] = useState<ProfileDraft>();
  const [baseline, setBaseline] = useState("");
  const active = useRef(true);
  const dirty = !!draft && JSON.stringify(draft) !== baseline;

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onDirty(dirty || busy);
  }, [dirty, busy, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setLoadError("");
    api<StorageProfile[]>("/storage-profiles")
      .then((profiles) => {
        if (live) setItems(profiles);
      })
      .catch((e: Error) => {
        if (live) setLoadError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [refresh]);

  function openEditor(profile?: StorageProfile) {
    if (busy || (profile && !profile.can_manage)) return;
    if (dirty && !confirm("放弃未保存的存储配置修改？")) return;
    const nextDraft = makeDraft(profile);
    setEditing(profile);
    setDraft(nextDraft);
    setBaseline(JSON.stringify(nextDraft));
    setError("");
    setNotice("");
  }
  function cancelEditor() {
    if (busy || (dirty && !confirm("放弃未保存的存储配置修改？"))) return;
    setDraft(undefined);
    setEditing(undefined);
    setError("");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    const parameters: Record<string, string> = {};
    for (const field of fields[draft.storage_type]) {
      const value = draft.parameters[field.key] || "";
      if (field.secret && editing?.has_secrets && !value) continue;
      if (!value.trim()) {
        setError(`请填写 ${field.label}`);
        return;
      }
      parameters[field.key] = field.secret ? value : value.trim();
    }
    if (!draft.name.trim()) {
      setError("请填写配置名称");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(
        editing ? profilePath(editing) : "/storage-profiles",
        editing ? "PUT" : "POST",
        {
          name: draft.name.trim(),
          storage_type: draft.storage_type,
          description: draft.description.trim(),
          enabled: draft.enabled,
          parameters,
          ...(editing ? { revision: editing.revision } : {}),
        },
      );
      if (!active.current) return;
      setNotice(editing ? "存储配置已保存" : "存储配置已创建");
      setDraft(undefined);
      setEditing(undefined);
      setRefresh((value) => value + 1);
    } catch (e) {
      if (active.current) setError((e as Error).message);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function manage(profile: StorageProfile, action: "toggle" | "delete") {
    if (busy || draft || !profile.can_manage) return;
    if (
      action === "delete" &&
      !confirm(
        `删除存储配置「${profile.name}」？仅删除平台保存的配置，不会删除实际存储后端、数据或文件系统。`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (action === "delete") {
        await api(
          `${profilePath(profile)}?revision=${profile.revision}`,
          "DELETE",
        );
      } else {
        await api(profilePath(profile), "PUT", {
          name: profile.name,
          storage_type: profile.storage_type,
          description: profile.description,
          enabled: !profile.enabled,
          parameters: profile.parameters,
          revision: profile.revision,
        });
      }
      if (!active.current) return;
      setNotice(
        action === "delete"
          ? "存储配置已删除"
          : profile.enabled
            ? "存储配置已禁用"
            : "存储配置已启用",
      );
      setRefresh((value) => value + 1);
    } catch (e) {
      if (active.current) {
        setError((e as Error).message);
        setRefresh((value) => value + 1);
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <div className="storage-profiles-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / STORAGE</p>
          <h1>存储管理</h1>
          <p className="muted">
            集中维护 S3 和 RADOS 存储配置，创建文件系统时按名称选择。
          </p>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={() => openEditor()}
        >
          新建存储配置
        </button>
      </header>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
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
      {draft && (
        <form className="panel storage-editor" onSubmit={save}>
          <div className="section-title">
            <h2>{editing ? "编辑存储配置" : "新建存储配置"}</h2>
            <span className="badge">{draft.storage_type.toUpperCase()}</span>
          </div>
          <p className="muted">
            {editing
              ? "存储类型创建后不可修改。"
              : "保存后，所有成员均可在创建文件系统时选择已启用的配置。"}
          </p>
          <fieldset disabled={busy}>
            <div className="form-grid">
              <label>
                配置名称
                <input
                  required
                  autoFocus
                  value={draft.name}
                  onChange={(event) =>
                    setDraft({ ...draft, name: event.target.value })
                  }
                />
              </label>
              <label>
                存储类型
                <select
                  value={draft.storage_type}
                  disabled={!!editing}
                  onChange={(event) => {
                    const type = event.target.value as StorageType;
                    setDraft({
                      ...draft,
                      storage_type: type,
                      parameters: blankParameters(type),
                    });
                  }}
                >
                  <option value="s3">S3</option>
                  <option value="rados">RADOS</option>
                </select>
              </label>
              <label className="storage-form-wide">
                说明（可选）
                <textarea
                  rows={2}
                  value={draft.description}
                  onChange={(event) =>
                    setDraft({ ...draft, description: event.target.value })
                  }
                />
              </label>
            </div>
            <h3>{draft.storage_type.toUpperCase()} 连接配置</h3>
            <div className="form-grid">
              {fields[draft.storage_type].map((field) => (
                <label key={field.key}>
                  {field.label}
                  <input
                    type={field.secret ? "password" : "text"}
                    required={!field.secret || !editing?.has_secrets}
                    autoComplete={field.secret ? "new-password" : "off"}
                    spellCheck={false}
                    placeholder={
                      field.secret && editing?.has_secrets
                        ? "留空保留已保存的密钥"
                        : field.placeholder
                    }
                    aria-describedby={
                      field.secret ? "storage-credentials-note" : undefined
                    }
                    value={draft.parameters[field.key] || ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        parameters: {
                          ...draft.parameters,
                          [field.key]: event.target.value,
                        },
                      })
                    }
                  />
                </label>
              ))}
            </div>
            <p
              id="storage-credentials-note"
              className="muted storage-credentials-note"
            >
              {editing?.has_secrets
                ? "已保存密钥不会回显；留空可保留原值，填写新值后将在保存时替换。"
                : "密钥保存后不会回显。"}
            </p>
            <label className="storage-enabled">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) =>
                  setDraft({ ...draft, enabled: event.target.checked })
                }
              />
              启用此配置
            </label>
            <p className="muted storage-help">
              禁用后不可用于新建文件系统，不影响已有文件系统。
            </p>
          </fieldset>
          <div className="actions">
            <button className="primary" disabled={busy}>
              {busy ? "正在保存…" : editing ? "保存修改" : "创建配置"}
            </button>
            <button type="button" disabled={busy} onClick={cancelEditor}>
              取消
            </button>
          </div>
        </form>
      )}
      <section
        className="panel storage-overview"
        aria-label="存储配置列表"
        aria-busy={loading}
      >
        <div className="storage-table-toolbar">
          <div>
            <h2>存储配置</h2>
            <p className="muted">
              所有成员可查看和使用；创建者和管理员可管理。
            </p>
          </div>
          <button
            disabled={loading || busy}
            onClick={() => setRefresh((value) => value + 1)}
          >
            刷新
          </button>
        </div>
        {loading && (
          <p role="status" className="storage-loading">
            正在读取存储配置…
          </p>
        )}
        <div className="storage-table-scroll">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>存储位置</th>
                <th>状态</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((profile) => (
                <tr key={profile.id}>
                  <td>
                    <strong>{profile.name}</strong>
                    {profile.description && (
                      <small className="muted storage-cell-detail">
                        {profile.description}
                      </small>
                    )}
                  </td>
                  <td>
                    <span className="badge">
                      {profile.storage_type.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span>
                      {profile.storage_type === "s3"
                        ? profile.parameters.s3_bucketname
                        : profile.parameters.rados_poolname}
                    </span>
                    <small className="muted storage-cell-detail">
                      {profile.storage_type === "s3"
                        ? profile.parameters.s3_endpoint
                        : profile.parameters.rados_mon}
                    </small>
                  </td>
                  <td>
                    <span
                      className={`badge ${profile.enabled ? "" : "storage-disabled"}`}
                    >
                      {profile.enabled ? "已启用" : "已禁用"}
                    </span>
                  </td>
                  <td className="storage-time">
                    <time dateTime={profile.updated_at}>
                      {updatedTime(profile.updated_at)}
                    </time>
                  </td>
                  <td>
                    {profile.can_manage ? (
                      <div className="storage-row-actions">
                        <button
                          disabled={busy}
                          onClick={() => openEditor(profile)}
                        >
                          编辑
                        </button>
                        <button
                          disabled={busy || !!draft}
                          onClick={() => manage(profile, "toggle")}
                        >
                          {profile.enabled ? "禁用" : "启用"}
                        </button>
                        <button
                          disabled={busy || !!draft}
                          onClick={() => manage(profile, "delete")}
                        >
                          删除
                        </button>
                      </div>
                    ) : (
                      <span className="muted">只读</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && !items.length && (
          <p className="empty">
            {loadError
              ? "存储配置未能加载，请点击刷新重试。"
              : "暂无存储配置，点击「新建存储配置」添加 S3 或 RADOS 存储。"}
          </p>
        )}
        {!!items.length && (
          <p className="storage-count muted">
            共 {items.length} 项配置 ·{" "}
            {items.filter((profile) => profile.enabled).length} 项已启用
          </p>
        )}
      </section>
    </div>
  );
}
