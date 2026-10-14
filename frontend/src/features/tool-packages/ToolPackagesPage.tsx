import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { MachineTools } from "./MachineTools";
type Source = {
  machine_id: string;
  directory: string;
  image: string;
  allow_cached: boolean;
  revision: number;
};
type Machine = {
  id: string;
  name: string;
  address: string;
  ssh_user: string;
  can_manage: boolean;
};
type View = {
  source: Source;
  configured: boolean;
  can_manage: boolean;
  machines: Machine[];
};
export function ToolPackagesPage() {
  const [view, setView] = useState<View>();
  const [source, setSource] = useState<Source>();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let active = true;
    api<View>("/tool-source")
      .then((value) => {
        if (active) {
          setView(value);
          setSource(value.source);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const updated = await api<Source>("/tool-source", "PUT", source);
      setSource(updated);
      setView((v) => (v ? { ...v, source: updated, configured: true } : v));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const machines = view?.machines || [];
  const selected = machines.find((m) => m.id === target);
  return (
    <section className="panel">
      <h2>工具包管理</h2>
      <p>
        选择目标机器和工具，一键完成获取、校验和部署，无需登录机器执行命令。
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!view ? (
        <p>正在读取工具来源…</p>
      ) : (
        <>
          {source && (
            <details open={!view.configured}>
              <summary>
                平台工具来源 · {view.configured ? "已配置" : "首次使用需保存"}
              </summary>
              <p className="muted">
                dtt 镜像地址来自 build.sh
                的发布仓库。优先从平台机器通过 scp 直传镜像，失败后由目标机器拉取，拉取超时为10分钟；启动脚本和其他工具从下方目录获取。
              </p>
              {view.can_manage ? (
                <form onSubmit={save} className="form-grid">
                  <label>
                    平台机器
                    <select
                      value={source.machine_id}
                      required
                      onChange={(e) =>
                        setSource({ ...source, machine_id: e.target.value })
                      }
                    >
                      <option value="">请选择平台机器</option>
                      {machines.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} · {m.ssh_user}@{m.address}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    平台工具目录
                    <input
                      value={source.directory}
                      required
                      onChange={(e) =>
                        setSource({ ...source, directory: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    dtt 镜像地址
                    <input
                      value={source.image}
                      required
                      onChange={(e) =>
                        setSource({ ...source, image: e.target.value })
                      }
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={source.allow_cached}
                      onChange={(e) =>
                        setSource({ ...source, allow_cached: e.target.checked })
                      }
                    />
                    平台也无法连接仓库时，允许使用平台已有镜像（可能不是最新）
                  </label>
                  <button
                    className="primary"
                    disabled={busy || !source.machine_id}
                  >
                    {busy ? "正在保存…" : "保存工具来源"}
                  </button>
                  {saved && <p role="status">工具来源已保存，可以部署。</p>}
                </form>
              ) : (
                <p>
                  平台目录：{source.directory}
                  <br />
                  镜像：{source.image}
                  {!view.configured && (
                    <>
                      <br />
                      请管理员保存平台工具来源。
                    </>
                  )}
                </p>
              )}
            </details>
          )}
          <section>
            <h3>部署工具</h3>
            <label>
              目标机器
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">请选择要部署的机器</option>
                {machines
                  .filter((m) => m.can_manage)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} · {m.address} · {m.ssh_user}
                    </option>
                  ))}
              </select>
            </label>
            {selected && (
              <MachineTools
                key={selected.id}
                machineId={selected.id}
                canManage={selected.can_manage && view.configured}
              />
            )}
            {!target && (
              <p className="muted">也可以从机器详情页的“测试工具”直接部署。</p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
