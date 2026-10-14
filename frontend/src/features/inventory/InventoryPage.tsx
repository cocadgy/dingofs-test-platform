import {MachineTools} from "../tool-packages/MachineTools";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import {
  MachineHardware,
  hardwareSummary,
  statusNames,
} from "./MachineHardware";
import { ConfigEditor } from "../configuration/ConfigEditor";
import { MachineUsage } from "./MachineUsage";
export const sections: Record<string, string> = {
  machines: "机器资源",
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
  description?: string;
  maxLength?: number;
};
const fields: Record<string, Field[]> = {
  machines: [
    {
      key: "name",
      label: "名称",
      maxLength: 120,
      description: "支持中文、英文和数字，最多 120 个字符；仅用于平台展示。",
    },
    { key: "address", label: "主机地址" },
    {
      key: "aliases",
      label: "主机别名",
      type: "aliases",
      optional: true,
      description:
        "用逗号或换行分隔，例如 dingo126、dingo126.novalocal。别名用于关联服务主机，不会改变 SSH 连接地址。",
    },
    { key: "ssh_port", label: "SSH 端口", type: "number" },
    { key: "ssh_user", label: "SSH 用户" },
    {
      key: "ssh_password",
      label: "SSH 密码（留空保留原密码）",
      type: "password",
      optional: true,
    },
    { key: "credential_ref", label: "凭据引用", optional: true },
    { key: "physical_id", label: "物理机标识", optional: true },
  ],
  clusters: [
    { key: "name", label: "名称" },
    { key: "external_name", label: "dingo 集群名称" },
    {
      key: "management_machine_id",
      label: "dingo 执行机器",
      source: "machines",
      description:
        "运行 dingo 管理命令的机器，可以是独立运维机，也可以是集群节点。",
    },
    { key: "os_user", label: "执行用户" },
    { key: "dingo_path", label: "dingo 工具路径" },
    { key: "config_dir", label: "dingo 配置目录" },
    { key: "credential_ref", label: "凭据引用", optional: true },
    {
      key: "machine_ids",
      label: "集群节点",
      description:
        "实际部署 DingoFS 服务的机器，可多选，也可包含上面的 dingo 执行机器。",
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
  userId,
  onDirty,
  detailOnly = false,
  initialMachineId,
  createMachine = false,
  onBack,
  onMachineSaved,
}: {
  kind: string;
  admin: boolean;
  userId?: string;
  onDirty: (v: boolean) => void;
  detailOnly?: boolean;
  initialMachineId?: string;
  createMachine?: boolean;
  onBack?: () => void;
  onMachineSaved?: (id: string) => void;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Row>();
  const canEdit =
    admin ||
    (kind === "machines" && !!userId && selected?.creator_id === userId);
  const [editing, setEditing] = useState(createMachine);
  const [values, setValues] = useState<Record<string, any>>(
    createMachine ? { ssh_port: 22, machine_ids: [] } : {},
  );
  const [detailLoading, setDetailLoading] = useState(!!initialMachineId);
  const [refs, setRefs] = useState<Record<string, Row[]>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string>();
  const [configDirty, setConfigDirty] = useState(false);
  useEffect(() => {
    if (!detailOnly || !initialMachineId) return;
    let live = true;
    setDetailLoading(true);
    api<Row>(`/machines/${encodeURIComponent(initialMachineId)}`)
      .then((row) => {
        if (live) setSelected(row);
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setDetailLoading(false);
      });
    return () => {
      live = false;
    };
  }, [detailOnly, initialMachineId]);
  async function refresh() {
    if (detailOnly) return;
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
  useEffect(() => {
    if (
      kind !== "machines" ||
      !selected ||
      (selected.collection_status !== "collecting" &&
        refreshingId !== selected.id)
    )
      return;
    const id = selected.id;
    let live = true;
    const timer = window.setInterval(() => {
      api<Row>(`/machines/${id}`)
        .then((row) => {
          if (live)
            setSelected((current) => (current?.id === id ? row : current));
        })
        .catch(() => {
          /* The refresh request reports its own failure. */
        });
    }, 2000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [kind, selected?.id, selected?.collection_status, refreshingId]);
  async function refreshHardware(trust = false) {
    if (
      !selected ||
      refreshingId ||
      (trust && !selected.ssh_host_trust?.pending)
    )
      return;
    const id = selected.id;
    setRefreshingId(id);
    setError("");
    try {
      let target = selected;
      if (trust) {
        target = await api<Row>(`/machines/${id}/trust-host-key`, "POST", {
          base_revision: selected.revision,
          challenge_id: selected.ssh_host_trust.pending.challenge_id,
        });
        setSelected((current) => (current?.id === id ? target : current));
      }
      const row = await api<Row>(`/machines/${id}/refresh-hardware`, "POST", {
        base_revision: target.revision,
      });
      setSelected((current) => (current?.id === id ? row : current));
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      try {
        const row = await api<Row>(`/machines/${id}`);
        setSelected((current) => (current?.id === id ? row : current));
      } catch {
        /* Preserve current detail if the connection is unavailable. */
      }
    } finally {
      setRefreshingId(undefined);
    }
  }
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
        ? Object.fromEntries(
            fields[kind].map((f) => [
              f.key,
              f.type === "aliases"
                ? (row[f.key] || []).join(", ")
                : (row[f.key] ?? ""),
            ]),
          )
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
        else if (f.type === "aliases")
          value = [
            ...new Set(
              String(value || "")
                .split(/[,，\n]+/)
                .map((v) => v.trim())
                .filter(Boolean),
            ),
          ];
        else value = value ?? "";
        body[f.key] = value;
      }
      if (kind === "machines")
        body.clear_ssh_password = values.clear_ssh_password === true;
      if (selected) body.base_revision = selected.revision;
      const row = await api<Row>(
        "/" + kind + (selected ? "/" + selected.id : ""),
        selected ? "PATCH" : "POST",
        body,
      );
      setEditing(false);
      setValues({});
      setSelected(row);
      await refresh();
      onMachineSaved?.(row.id);
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
          <h1>
            {detailOnly
              ? createMachine
                ? "登记机器资源"
                : "机器资源详情"
              : sections[kind]}
          </h1>
          <p className="muted">
            {kind === "clusters"
              ? "登记已有集群及管理入口。运行状态尚未探测，运维操作将在后续阶段开放。"
              : "集中管理测试所需的资源与配置。"}
          </p>
        </div>
        {detailOnly ? (
          <button onClick={onBack} disabled={busy}>
            返回机器概览
          </button>
        ) : (
          (admin || kind === "machines") && (
            <button className="primary" onClick={() => edit()}>
              登记{sections[kind]}
            </button>
          )
        )}
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div
        className={detailOnly ? "machine-detail-layout" : "inventory-layout"}
      >
        {!detailOnly && (
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
                      setValues({});
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
                  {kind === "machines" && (
                    <small>
                      {hardwareSummary(row)} ·{" "}
                      {statusNames[row.collection_status || "never"] || "未知"}
                    </small>
                  )}
                </button>
              ))}
              {!items.length && (
                <p className="empty">暂无资源，请先登记所需的机器或集群。</p>
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
        )}
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
                        aria-describedby={
                          f.description ? `${kind}-${f.key}-help` : undefined
                        }
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
                            {f.source === "clusters" &&
                            (refs.clusters || []).filter(
                              (c) => c.name === r.name,
                            ).length > 1
                              ? `${r.name} · ${r.os_user} · ${(refs.machines || []).find((m) => m.id === r.management_machine_id)?.name || r.management_machine_id}`
                              : r.name}
                          </option>
                        ))}
                      </select>
                    ) : f.type === "aliases" ? (
                      <textarea
                        aria-label={f.label}
                        rows={2}
                        value={values[f.key] ?? ""}
                        onChange={(e) =>
                          setValues({ ...values, [f.key]: e.target.value })
                        }
                      />
                    ) : (
                      <input
                        aria-label={f.label}
                        aria-describedby={
                          f.description ? `${kind}-${f.key}-help` : undefined
                        }
                        maxLength={f.maxLength}
                        required={!f.optional}
                        type={f.type || "text"}
                        autoComplete={
                          f.type === "password" ? "new-password" : undefined
                        }
                        value={values[f.key] ?? ""}
                        onChange={(e) =>
                          setValues({ ...values, [f.key]: e.target.value })
                        }
                      />
                    )}
                    {f.description && (
                      <small className="muted" id={`${kind}-${f.key}-help`}>
                        {f.description}
                      </small>
                    )}
                  </label>
                ))}
              </div>
              {kind === "machines" && (
                <>
                  <p className="muted">
                    {selected?.has_ssh_password
                      ? "已配置 SSH 密码，留空不会修改。"
                      : "未配置 SSH 密码，采集前需要填写。"}
                  </p>
                  {selected?.has_ssh_password && (
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={values.clear_ssh_password === true}
                        onChange={(e) =>
                          setValues({
                            ...values,
                            clear_ssh_password: e.target.checked,
                          })
                        }
                      />
                      清除已保存的 SSH 密码
                    </label>
                  )}
                </>
              )}
              <div className="actions">
                <button className="primary" disabled={busy}>
                  保存资源
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (detailOnly && createMachine && !selected) {
                      onBack?.();
                      return;
                    }
                    if (leave()) {
                      setEditing(false);
                      setValues({});
                    }
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
                {fields[kind]
                  .filter((f) => f.type !== "password")
                  .map((f) => (
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
              {kind === "machines" &&
                Object.keys(selected.alias_conflicts || {}).length > 0 && (
                  <p role="alert" className="remote-notice">
                    别名存在匹配冲突：
                    {Object.entries(
                      selected.alias_conflicts as Record<
                        string,
                        { name: string; address: string }[]
                      >,
                    )
                      .map(
                        ([alias, rows]) =>
                          `${alias}（${rows.map((row) => `${row.name} · ${row.address}`).join("、")}）`,
                      )
                      .join("；")}
                    。请调整别名，存在冲突的服务主机不能唯一关联机器。
                  </p>
                )}
              {kind === "machines" && (
                <p>
                  SSH 密码：{selected.has_ssh_password ? "已配置" : "未配置"}
                </p>
              )}
              {kind === "machines" && canEdit && !selected.archived && selected.has_ssh_password && (
                <p><a className="button" href={`#/machines/${encodeURIComponent(selected.id)}/terminal`}
                  target="_blank" rel="noopener noreferrer">打开 SSH 终端</a></p>
              )}
              {kind === "machines" && canEdit && !selected.archived && !selected.has_ssh_password && (
                <p className="muted">配置 SSH 密码后可打开网页终端。</p>
              )}
              {canEdit && (
                <div className="actions">
                  <button onClick={() => edit(selected)}>编辑资源</button>
                  <button onClick={archive} disabled={busy}>
                    {selected.archived ? "恢复资源" : "归档资源"}
                  </button>
                </div>
              )}
              {kind === "machines" && detailOnly && <MachineTools key={selected.id} machineId={selected.id} canManage={canEdit && !selected.archived && !selected.maintenance} />}
              {kind === "machines" && detailOnly && <MachineUsage machineId={selected.id} />}
              {kind === "machines" && (
                <MachineHardware
                  machine={selected}
                  canEdit={canEdit}
                  refreshing={refreshingId === selected.id}
                  onRefresh={() => refreshHardware()}
                  onTrust={() => refreshHardware(true)}
                />
              )}
              {["clusters", "environments"].includes(kind) &&
                !selected.archived && (
                  <ConfigEditor
                    key={selected.id}
                    kind={kind === "clusters" ? "cluster" : "environment"}
                    id={selected.id}
                    admin={canEdit}
                    onDirty={setConfigDirty}
                  />
                )}
            </>
          ) : (
            <div className="empty">
              <h2>
                {detailOnly
                  ? detailLoading
                    ? "正在读取机器信息…"
                    : "无法读取机器信息"
                  : "选择一项资源"}
              </h2>
              <p>
                {detailOnly
                  ? "可返回机器概览重新选择。"
                  : "查看关联信息、维护配置与版本。"}
              </p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
