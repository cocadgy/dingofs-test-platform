import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ConfigEditor } from "../configuration/ConfigEditor";
export const sections: Record<string, string> = {
  machines: "机器资源",
  "management-contexts": "管理上下文",
  clusters: "集群管理",
  environments: "测试环境",
};
type Row = {
  id: string;
  name: string;
  revision: number;
  archived: boolean;
  [key: string]: any;
};
type Field = {
  key: string;
  label: string;
  type?: string;
  source?: string;
  optional?: boolean;
};
const fields: Record<string, Field[]> = {
  machines: [
    { key: "name", label: "名称" },
    { key: "address", label: "主机地址" },
    { key: "ssh_port", label: "SSH 端口", type: "number" },
    { key: "ssh_user", label: "SSH 用户" },
    { key: "credential_ref", label: "凭据引用", optional: true },
    { key: "physical_id", label: "物理机标识", optional: true },
  ],
  "management-contexts": [
    { key: "name", label: "名称" },
    { key: "machine_id", label: "管理机器", source: "machines" },
    { key: "os_user", label: "执行用户" },
    { key: "dingo_path", label: "dingo 工具路径" },
    { key: "config_dir", label: "dingo 配置目录" },
    { key: "credential_ref", label: "凭据引用", optional: true },
  ],
  clusters: [
    { key: "name", label: "名称" },
    { key: "context_id", label: "管理上下文", source: "management-contexts" },
    { key: "external_name", label: "dingo 集群名称" },
    {
      key: "machine_ids",
      label: "关联机器",
      source: "machines",
      type: "multiple",
    },
  ],
  environments: [
    { key: "name", label: "名称" },
    { key: "cluster_id", label: "关联集群", source: "clusters" },
    {
      key: "machine_ids",
      label: "测试机器",
      source: "machines",
      type: "multiple",
    },
  ],
};
export function InventoryPage({
  kind,
  admin,
  onDirty,
}: {
  kind: string;
  admin: boolean;
  onDirty: (v: boolean) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Row>();
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, any>>({});
  const [refs, setRefs] = useState<Record<string, Row[]>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [configDirty, setConfigDirty] = useState(false);
  async function refresh() {
    const r = await api<{ items: Row[]; total: number }>(
      `/${kind}?limit=20&offset=${offset}&q=${encodeURIComponent(query)}`,
    );
    setItems(r.items);
    setTotal(r.total);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [kind, offset, query]);
  useEffect(() => {
    onDirty(editing || configDirty);
  }, [editing, configDirty, onDirty]);
  useEffect(() => {
    let live = true;
    const sources = [
      ...new Set(fields[kind].flatMap((f) => (f.source ? [f.source] : []))),
    ];
    Promise.all(
      sources.map(async (s) => {
        const all: Row[] = [];
        let start = 0;
        while (true) {
          const r = await api<{ items: Row[]; total: number }>(
            `/${s}?limit=200&offset=${start}`,
          );
          all.push(...r.items.filter((x) => !x.archived));
          start += r.items.length;
          if (!r.items.length || start >= r.total) break;
        }
        return [s, all] as const;
      }),
    )
      .then((data) => {
        if (live) setRefs(Object.fromEntries(data));
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [kind, items.length]);
  function leave() {
    return (
      !(editing || configDirty) || window.confirm("有未保存修改，确定离开？")
    );
  }
  function edit(row?: Row) {
    if (!leave()) return;
    setSelected(row);
    setValues(
      row
        ? Object.fromEntries(fields[kind].map((f) => [f.key, row[f.key] ?? ""]))
        : { ssh_port: 22, machine_ids: [] },
    );
    setEditing(true);
    setError("");
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: Record<string, any> = {};
      for (const f of fields[kind]) {
        let value = values[f.key];
        if (f.key === "physical_id" && !value) value = null;
        else if (f.type === "number") value = Number(value);
        else if (f.type === "multiple") value = value || [];
        else value = value ?? "";
        body[f.key] = value;
      }
      if (selected) body.base_revision = selected.revision;
      const row = await api<Row>(
        "/" + kind + (selected ? "/" + selected.id : ""),
        selected ? "PATCH" : "POST",
        body,
      );
      setEditing(false);
      setSelected(row);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function archive() {
    if (
      !selected ||
      !leave() ||
      !window.confirm(
        `确认${selected.archived ? "恢复" : "归档"}「${selected.name}」？`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      setSelected(
        await api<Row>(`/${kind}/${selected.id}`, "PATCH", {
          base_revision: selected.revision,
          archived: !selected.archived,
        }),
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / INVENTORY</p>
          <h1>{sections[kind]}</h1>
          <p className="muted">
            {kind === "clusters"
              ? "登记已有集群及管理入口。运行状态尚未探测，运维操作将在后续阶段开放。"
              : "集中管理测试所需的资源与配置。"}
          </p>
        </div>
        {admin && (
          <button className="primary" onClick={() => edit()}>
            登记{sections[kind]}
          </button>
        )}
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="inventory-layout">
        <section className="panel">
          <label className="search">
            搜索名称
            <input
              placeholder="输入资源名称"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          <div className="resource-list">
            {items.map((row) => (
              <button
                key={row.id}
                className={
                  "resource " + (selected?.id === row.id ? "selected" : "")
                }
                onClick={() => {
                  if (leave()) {
                    setSelected(row);
                    setEditing(false);
                    setError("");
                  }
                }}
              >
                <strong>{row.name}</strong>
                <span>
                  {row.archived
                    ? "已归档"
                    : kind === "clusters"
                      ? "尚未探测"
                      : kind === "machines"
                        ? row.address
                        : "已登记"}
                </span>
              </button>
            ))}
            {!items.length && (
              <p className="empty">暂无资源，先登记机器和管理上下文。</p>
            )}
          </div>
          <div className="pagination">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              上一页
            </button>
            <span>共 {total} 条</span>
            <button
              disabled={offset + 20 >= total}
              onClick={() => setOffset(offset + 20)}
            >
              下一页
            </button>
          </div>
        </section>
        <section className="panel detail">
          {editing ? (
            <form onSubmit={save}>
              <h2>
                {selected ? "编辑" : "登记"}
                {sections[kind]}
              </h2>
              <div className="form-grid">
                {fields[kind].map((f) => (
                  <label key={f.key}>
                    {f.label}
                    {f.source ? (
                      <select
                        aria-label={f.label}
                        required={!f.optional && f.type !== "multiple"}
                        multiple={f.type === "multiple"}
                        value={
                          values[f.key] ?? (f.type === "multiple" ? [] : "")
                        }
                        onChange={(e) =>
                          setValues({
                            ...values,
                            [f.key]:
                              f.type === "multiple"
                                ? Array.from(
                                    e.target.selectedOptions,
                                    (o) => o.value,
                                  )
                                : e.target.value,
                          })
                        }
                      >
                        {f.type !== "multiple" && (
                          <option value="">请选择</option>
                        )}
                        {(refs[f.source] || []).map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        required={!f.optional}
                        type={f.type || "text"}
                        value={values[f.key] ?? ""}
                        onChange={(e) =>
                          setValues({ ...values, [f.key]: e.target.value })
                        }
                      />
                    )}
                  </label>
                ))}
              </div>
              <div className="actions">
                <button className="primary" disabled={busy}>
                  保存资源
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (leave()) setEditing(false);
                  }}
                >
                  取消
                </button>
              </div>
            </form>
          ) : selected ? (
            <>
              <div className="section-title">
                <h2>{selected.name}</h2>
                <span className="badge">修订 {selected.revision}</span>
              </div>
              <dl>
                {fields[kind].map((f) => (
                  <div key={f.key}>
                    <dt>{f.label}</dt>
                    <dd>
                      {f.source
                        ? f.type === "multiple"
                          ? (selected[f.key] as string[])
                              .map(
                                (id) =>
                                  (refs[f.source!] || []).find(
                                    (x) => x.id === id,
                                  )?.name || id,
                              )
                              .join("、")
                          : (refs[f.source] || []).find(
                              (x) => x.id === selected[f.key],
                            )?.name || selected[f.key]
                        : String(selected[f.key] ?? "—")}
                    </dd>
                  </div>
                ))}
              </dl>
              {admin && (
                <div className="actions">
                  <button onClick={() => edit(selected)}>编辑资源</button>
                  <button onClick={archive} disabled={busy}>
                    {selected.archived ? "恢复资源" : "归档资源"}
                  </button>
                </div>
              )}
              {["clusters", "environments"].includes(kind) &&
                !selected.archived && (
                  <ConfigEditor
                    key={selected.id}
                    kind={kind === "clusters" ? "cluster" : "environment"}
                    id={selected.id}
                    admin={admin}
                    onDirty={setConfigDirty}
                  />
                )}
            </>
          ) : (
            <div className="empty">
              <h2>选择一项资源</h2>
              <p>查看关联信息、维护配置与版本。</p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
