import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { RemoteTarget, RemoteTargets } from "./types";
import { useRemoteSession } from "./useRemoteSession";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { TerminalSurface, type TerminalWriter } from "./TerminalSurface";
export function TerminalPage({
  clusterId,
  machineId,
  admin,
  userId,
}: {
  clusterId?: string;
  machineId: string;
  admin: boolean;
  userId?: string;
}) {
  const [target, setTarget] = useState<RemoteTarget>();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const writer = useRef<TerminalWriter | undefined>(undefined);
  const pending = useRef<string[]>([]);
  const bytes = useRef(0);
  const dimensions = useRef({ cols: 100, rows: 30 });
  const remote = useRemoteSession({
    onText: (event) => {
      const size = new TextEncoder().encode(event.text).length;
      bytes.current += size;
      if (bytes.current > 1024 * 1024) {
        setError("终端输出超过浏览器处理速度，连接已断开。");
        pending.current = [];
        remote.close();
        return;
      }
      if (writer.current)
        writer.current(event.text, () => {
          bytes.current -= size;
        });
      else pending.current.push(event.text);
    },
    onOpen: () => {
      remote.send({ type: "resize", ...dimensions.current });
    },
  });
  useEffect(() => {
    let live = true;
    if (!clusterId) {
      api<{ id: string; name: string; address: string; ssh_port: number; ssh_user: string;
        creator_id: string | null; archived: boolean; has_ssh_password: boolean }>(
        `/machines/${encodeURIComponent(machineId)}`,
      ).then((machine) => {
        if (!live) return;
        if (machine.archived || (!admin && (!userId || machine.creator_id !== userId))) {
          setError("无权连接此机器的网页终端。");
        } else if (!machine.has_ssh_password) {
          setError("此机器尚未配置 SSH 密码。");
        } else {
          setName(machine.name);
          setTarget({ machine_id: machine.id, name: machine.name,
            address: machine.address, ssh_port: machine.ssh_port,
            ssh_user: machine.ssh_user, service_ids: [], can_read_logs: false });
        }
      }).catch((e) => { if (live) setError(e.message); });
      return () => { live = false; };
    }
    if (!admin) return () => { live = false; };
    Promise.all([
      api<{ name: string }>(`/clusters/${encodeURIComponent(clusterId)}`),
      api<RemoteTargets>(
        `/clusters/${encodeURIComponent(clusterId)}/remote-targets`,
      ),
    ])
      .then(([cluster, targets]) => {
        if (!live) return;
        setName(cluster.name);
        const row = targets.items.find((item) => item.machine_id === machineId);
        if (row) setTarget(row);
        else
          setError(
            "该机器不属于当前集群允许连接的目标，请返回集群详情重新选择。",
          );
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [clusterId, machineId, admin, userId]);
  async function connect() {
    if (
      !target ||
      !window.confirm(
        `连接机器「${target.name}」\n地址：${target.address}:${target.ssh_port ?? 22}\nSSH 用户：${target.ssh_user}\n\n终端具有该系统用户的真实权限，可以操作同机其他集群。确认连接？`,
      )
    )
      return;
    setError("");
    writer.current = undefined;
    pending.current = [];
    bytes.current = 0;
    setAttempt((value) => value + 1);
    await remote.start({
      kind: "terminal",
      ...(clusterId ? { cluster_id: clusterId } : {}),
      machine_id: machineId,
      confirmed: true,
      ...dimensions.current,
    });
  }
  if (clusterId && !admin)
    return (
      <section className="panel">
        <h1>管理员终端</h1>
        <p role="alert">仅管理员可连接网页 SSH 终端。</p>
        <a href={`#/clusters/${encodeURIComponent(clusterId)}`}>返回集群详情</a>
      </section>
    );
  const backHref = clusterId
    ? `#/clusters/${encodeURIComponent(clusterId)}`
    : `#/machines/${encodeURIComponent(machineId)}`;
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / SSH TERMINAL</p>
          <h1>{name || (clusterId ? "集群" : "机器")} · SSH 终端</h1>
          <p>
            {target
              ? `${target.name} · ${target.address}:${target.ssh_port ?? 22} · SSH 用户 ${target.ssh_user}`
              : "正在读取连接目标…"}
          </p>
        </div>
        <a
          className="button"
          href={backHref}
        >
          {clusterId ? "返回集群详情" : "返回机器详情"}
        </a>
      </header>
      <section className="panel remote-terminal-panel">
        <p>
          此终端使用机器登记的 SSH
          用户，具有该系统用户的真实权限，包括同机其他集群。连接后可自行输入命令。
        </p>
        <div className="actions">
          <button
            className="primary"
            disabled={!target || remote.active}
            onClick={connect}
          >
            {attempt ? "重新连接" : "连接终端"}
          </button>
          <button disabled={!remote.active} onClick={remote.close}>
            断开连接
          </button>
        </div>
        <RemoteSessionStatus remote={remote} />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {attempt > 0 ? (
          <TerminalSurface
            key={attempt}
            onReady={(write) => {
              writer.current = write;
              if (!write) return;
              for (const text of pending.current) {
                const size = new TextEncoder().encode(text).length;
                write(text, () => {
                  bytes.current -= size;
                });
              }
              pending.current = [];
            }}
            onData={(data) => {
              remote.send({ type: "input", data });
            }}
            onResize={(cols, rows) => {
              dimensions.current = { cols, rows };
              remote.send({ type: "resize", cols, rows });
            }}
            onError={(message) => {
              setError(message);
              remote.close();
            }}
          />
        ) : (
          <div className="terminal-placeholder">
            点击“连接终端”并确认目标后开始会话
          </div>
        )}
        <p className="muted">
          关闭页面会断开连接；不会自动重连、重放输入或执行预设命令。
        </p>
      </section>
    </>
  );
}
