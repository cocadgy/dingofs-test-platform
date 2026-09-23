import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { OperationAuthDialog } from "./OperationAuthDialog";
import { type Operation, type ImportResult } from "./types";
type Machine = {
  id: string;
  name: string;
  address: string;
  ssh_user: string;
  revision: number;
  archived: boolean;
  creator_id?: string | null;
};
export function DiscoverClusters({
  admin = false,
  userId,
  onImported,
  onClose,
}: {
  admin?: boolean;
  userId?: string;
  onImported: (ids: string[]) => void;
  onClose: () => void;
}) {
  const [machines, setMachines] = useState<Machine[]>([]),
    [mid, setMid] = useState(""),
    [user, setUser] = useState(""),
    [op, setOp] = useState<Operation>(),
    [selected, setSelected] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [imports, setImports] = useState<ImportResult>(),
    [query, setQuery] = useState("");
  const live = useRef(true);
  const generation = useRef(0);
  useEffect(() => {
    live.current = true;
    let active = true;
    (async () => {
      const all: Machine[] = [];
      let offset = 0;
      while (true) {
        const r = await api<{ items: Machine[]; total: number }>(
          `/machines?limit=200&offset=${offset}`,
        );
        if (!active) return;
        all.push(
          ...r.items.filter(
            (m) =>
              !m.archived && (admin || (!!userId && m.creator_id === userId)),
          ),
        );
        offset += r.items.length;
        if (!r.items.length || offset >= r.total) break;
      }
      setMachines(all);
    })().catch((e) => {
      if (active) setError(e.message);
    });
    return () => {
      active = false;
      live.current = false;
    };
  }, [admin, userId]);
  const names =
    (op?.state === "succeeded"
      ? (op.result?.names as string[] | undefined)
      : undefined) || [];
  const working =
    busy ||
    (!!op && ["pending", "running", "needs_password"].includes(op.state));
  async function discover(e: React.FormEvent) {
    e.preventDefault();
    const m = machines.find((m) => m.id === mid);
    if (!m) return;
    setBusy(true);
    setError("");
    setImports(undefined);
    setSelected([]);
    const gen = ++generation.current;
    try {
      const next = await api<Operation>("/cluster-discoveries", "POST", {
        machine_id: mid,
        machine_revision: m.revision,
        target_user: user,
      });
      if (live.current && gen === generation.current) setOp(next);
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  async function importing() {
    if (!op) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<ImportResult>(
        `/cluster-discoveries/${op.id}/import`,
        "POST",
        { names: selected },
      );
      if (!live.current) return;
      setImports(result);
      if (!result.needs_confirmation.length)
        onImported([...result.created, ...result.existing].map((r) => r.id));
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  async function bind(id: string, revision: number, name: string) {
    if (
      !op ||
      !confirm("确认把已有集群绑定到本次发现的入口？原环境和配置历史将保留。")
    )
      return;
    setBusy(true);
    try {
      await api(`/clusters/${id}/rebind`, "POST", {
        base_revision: revision,
        discovery_id: op.id,
        name,
      });
      if (live.current) onImported([id]);
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  async function close() {
    if (
      op &&
      ["pending", "running", "needs_password", "needs_trust"].includes(op.state)
    ) {
      try {
        await api(`/cluster-operations/${op.id}/cancel`, "POST");
      } catch (e) {
        setError((e as Error).message);
        return;
      }
    }
    onClose();
  }
  return (
    <section className="panel cluster-discover" aria-label="发现集群">
      <div className="section-title">
        <h2>发现集群</h2>
        <button onClick={close} disabled={busy}>
          关闭
        </button>
      </div>
      <p className="muted">
        使用机器的 SSH 账号连接，再切换到指定用户执行
        dingo。只发现已有集群，不创建远端集群。
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form onSubmit={discover}>
        <div className="form-grid">
          <label>
            执行机器
            <select
              required
              value={mid}
              disabled={working}
              onChange={(e) => {
                setMid(e.target.value);
                setUser(
                  machines.find((m) => m.id === e.target.value)?.ssh_user || "",
                );
                setOp(undefined);
                setImports(undefined);
              }}
            >
              <option value="">请选择机器</option>
              {machines.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} · {m.address}
                </option>
              ))}
            </select>
          </label>
          <label>
            执行用户
            <input
              required
              pattern="[a-zA-Z0-9_.-]+"
              maxLength={80}
              value={user}
              disabled={working}
              onChange={(e) => {
                setUser(e.target.value);
                setOp(undefined);
                setImports(undefined);
              }}
            />
          </label>
        </div>
        <button className="primary" disabled={working}>
          查询集群
        </button>
      </form>
      {op && <OperationAuthDialog operation={op} onChange={setOp} />}
      {op?.state === "succeeded" && (
        <>
          <h3>发现 {names.length} 个集群</h3>
          <label>
            搜索集群
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="actions">
            <button onClick={() => setSelected(names)}>全选</button>
            <button onClick={() => setSelected([])}>清空选择</button>
          </div>
          <div className="discovered-list">
            {names
              .filter((n) => n.toLowerCase().includes(query.toLowerCase()))
              .map((n) => (
                <label key={n} className="checkbox-label">
                  <input
                    type="checkbox"
                    aria-label={n}
                    checked={selected.includes(n)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, n]
                          : selected.filter((x) => x !== n),
                      )
                    }
                  />
                  {n}
                  {(
                    op.result?.registered_names as string[] | undefined
                  )?.includes(n) && <small>已登记</small>}
                </label>
              ))}
          </div>
          {!names.length && <p>该用户下没有发现集群。</p>}
          <button
            className="primary"
            disabled={busy || !selected.length}
            onClick={importing}
          >
            导入所选集群
          </button>
        </>
      )}
      {imports?.needs_confirmation.map((item) => (
        <div className="cluster-operation" key={item.name}>
          <h3>{item.name}：需要确认管理入口</h3>
          <p>已有登记配置与本次发现不同，不会自动合并。</p>
          {item.candidates.map((c) => (
            <div key={c.id}>
              <span>
                {c.name} · {c.config_dir}
                {c.archived ? " · 已归档" : ""}
              </span>
              <button
                disabled={busy || c.archived}
                onClick={() => bind(c.id, c.revision, item.name)}
              >
                确认绑定已有集群
              </button>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}
