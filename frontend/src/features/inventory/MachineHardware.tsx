import { useState } from "react";
type Hardware = {
  cpu?: {
    model?: string | null;
    logical_cores?: number;
    physical_cores?: number | null;
  } | null;
  memory?: { total_bytes: number } | null;
  disks?:
    | {
        name: string;
        type: string;
        size_bytes: number;
        model?: string | null;
        rotational?: boolean | null;
      }[]
    | null;
  filesystems?:
    | {
        source: string;
        mountpoint: string;
        total_bytes: number;
        available_bytes: number;
        same_filesystem_as?: string | null;
      }[]
    | null;
  interfaces?:
    | {
        name: string;
        mac?: string | null;
        addresses: string[];
        state: string;
        mtu: number;
        speed_mbps?: number | null;
      }[]
    | null;
  rdma?: { device: string; port: number; interfaces: string[] }[] | null;
  warnings?: string[];
};
export function bytes(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "未知";
  if (value < 1024) return `${value} B`;
  for (const [scale, unit] of [
    [1024 ** 4, "TiB"],
    [1024 ** 3, "GiB"],
    [1024 ** 2, "MiB"],
    [1024, "KiB"],
  ] as const) {
    if (value >= scale) return `${(value / scale).toFixed(2)} ${unit}`;
  }
  return "未知";
}
export function hardwareSummary(machine: Record<string, any>) {
  const h: Hardware | undefined =
    machine.hardware_info || machine.last_attempt_info;
  if (!h) return "尚无硬件信息";
  const disks = h.disks?.filter((d) => d.type === "disk");
  return `${h.cpu?.logical_cores ?? "未知"} 逻辑核 · 内存 ${bytes(h.memory?.total_bytes)} · 磁盘 ${disks?.length ? bytes(disks.reduce((n, d) => n + d.size_bytes, 0)) : "未知"}`;
}
export const statusNames: Record<string, string> = {
  never: "尚未采集",
  needs_trust: "等待确认 SSH 指纹",
  collecting: "采集中",
  success: "采集成功",
  partial: "部分信息可用",
  failed: "采集失败",
  interrupted: "采集中断",
};
function time(value?: string) {
  return value ? new Date(value).toLocaleString() : "—";
}
function Snapshot({ info, title }: { info: Hardware; title: string }) {
  return (
    <section className="hardware-snapshot">
      <h4>{title}</h4>
      <dl className="hardware-overview">
        <div>
          <dt>CPU 型号</dt>
          <dd>{info.cpu?.model || "未知"}</dd>
        </div>
        <div>
          <dt>逻辑 CPU 核数</dt>
          <dd>{info.cpu?.logical_cores ?? "未知"}</dd>
        </div>
        <div>
          <dt>物理 CPU 核数</dt>
          <dd>{info.cpu?.physical_cores ?? "未知"}</dd>
        </div>
        <div>
          <dt>总内存</dt>
          <dd>{bytes(info.memory?.total_bytes)}</dd>
        </div>
      </dl>
      <h4>磁盘与块设备</h4>
      {info.disks?.length ? (
        <div className="hardware-table">
          <table>
            <thead>
              <tr>
                <th>设备</th>
                <th>类型</th>
                <th>容量</th>
                <th>型号</th>
                <th>介质</th>
              </tr>
            </thead>
            <tbody>
              {info.disks.map((d) => (
                <tr key={d.name}>
                  <td>{d.name}</td>
                  <td>{d.type}</td>
                  <td>{bytes(d.size_bytes)}</td>
                  <td>{d.model || "未知"}</td>
                  <td>
                    {d.rotational == null
                      ? "未知"
                      : d.rotational
                        ? "旋转磁盘"
                        : "非旋转"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">无可用磁盘信息</p>
      )}
      <p className="muted">
        容量摘要只累计 disk 类型设备；分区、LVM 和挂载点不重复计入。
      </p>
      <h4>挂载文件系统</h4>
      {info.filesystems?.length ? (
        <div className="hardware-table">
          <table>
            <thead>
              <tr>
                <th>挂载点</th>
                <th>来源</th>
                <th>总量</th>
                <th>可用</th>
                <th>共享容量</th>
              </tr>
            </thead>
            <tbody>
              {info.filesystems.map((f, i) => (
                <tr key={i}>
                  <td>{f.mountpoint}</td>
                  <td>{f.source}</td>
                  <td>{bytes(f.total_bytes)}</td>
                  <td>{bytes(f.available_bytes)}</td>
                  <td>
                    {f.same_filesystem_as ? `同 ${f.same_filesystem_as}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">无可用挂载信息</p>
      )}
      <h4>网卡</h4>
      {info.interfaces?.length ? (
        <div className="hardware-table">
          <table>
            <thead>
              <tr>
                <th>名称 / MAC</th>
                <th>IP 地址</th>
                <th>状态</th>
                <th>速率</th>
                <th>MTU</th>
              </tr>
            </thead>
            <tbody>
              {info.interfaces.map((n) => (
                <tr key={n.name}>
                  <td>
                    {n.name}
                    <small>{n.mac || "未知"}</small>
                  </td>
                  <td>
                    {n.addresses.length
                      ? n.addresses.map((a) => <div key={a}>{a}</div>)
                      : "无 IP"}
                  </td>
                  <td>{n.state}</td>
                  <td>
                    {n.speed_mbps == null ? "未知" : `${n.speed_mbps} Mbps`}
                  </td>
                  <td>{n.mtu}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">无可用网卡信息</p>
      )}
      <h4>RDMA</h4>
      {info.rdma?.length ? (
        <div className="hardware-table">
          <table>
            <thead>
              <tr>
                <th>设备</th>
                <th>端口</th>
                <th>对应网卡</th>
              </tr>
            </thead>
            <tbody>
              {info.rdma.map((r) => (
                <tr key={`${r.device}-${r.port}`}>
                  <td>{r.device}</td>
                  <td>{r.port}</td>
                  <td>{r.interfaces.join("、") || "未知"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          {info.rdma ? "未发现 RDMA 设备" : "RDMA 信息不可用"}
        </p>
      )}
      {!!info.warnings?.length && (
        <ul className="hardware-warnings">
          {info.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
type PendingTrust = {
  challenge_id: string;
  host: string;
  port: number;
  key_type: string;
  fingerprint: string;
  previous_fingerprint?: string | null;
  expires_at: string;
};
function HostTrustPrompt({
  pending,
  canEdit,
  busy,
  onTrust,
}: {
  pending: PendingTrust;
  canEdit: boolean;
  busy: boolean;
  onTrust?: () => void;
}) {
  const [checked, setChecked] = useState(false);
  const expired = new Date(pending.expires_at).getTime() <= Date.now();
  const changed = !!pending.previous_fingerprint;
  return (
    <section
      className={"host-trust-prompt" + (changed ? " changed" : "")}
      aria-label="SSH 主机身份确认"
    >
      <h4>{changed ? "SSH 主机密钥已变化" : "首次连接：确认 SSH 主机身份"}</h4>
      <p>
        {changed
          ? "连接已停止。机器重装或密钥更换可能导致指纹变化，请核实后再信任新密钥。"
          : "请在目标机器的可信控制台核对 SSH 主机公钥指纹，确认一致后继续。"}
      </p>
      <dl>
        <div>
          <dt>主机地址</dt>
          <dd>
            {pending.host}:{pending.port}
          </dd>
        </div>
        <div>
          <dt>密钥类型</dt>
          <dd>{pending.key_type}</dd>
        </div>
        {pending.previous_fingerprint && (
          <div>
            <dt>原指纹</dt>
            <dd>
              <code>{pending.previous_fingerprint}</code>
            </dd>
          </div>
        )}
        <div>
          <dt>{changed ? "新指纹" : "SSH 指纹"}</dt>
          <dd>
            <code>{pending.fingerprint}</code>
          </dd>
        </div>
      </dl>
      {canEdit ? (
        <>
          {expired ? (
            <p>本次指纹确认已过期，请重新点击“更新机器信息”。</p>
          ) : (
            <p className="muted">
              确认有效期至 {time(pending.expires_at)}。确认前不会向该主机发送
              SSH 密码。
            </p>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={checked}
              disabled={busy || expired}
              onChange={(e) => setChecked(e.target.checked)}
            />
            我已通过可信渠道核对该机器的 SSH 指纹
          </label>
          <button
            className="primary"
            disabled={!checked || busy || expired || !onTrust}
            onClick={onTrust}
          >
            {changed ? "信任新密钥并继续" : "信任并继续"}
          </button>
        </>
      ) : (
        <p>请管理员核对并确认指纹后继续采集。</p>
      )}
    </section>
  );
}
export function MachineHardware({
  machine,
  canEdit,
  refreshing,
  onRefresh,
  onTrust,
}: {
  machine: Record<string, any>;
  canEdit: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onTrust?: () => void;
}) {
  const collecting = refreshing || machine.collection_status === "collecting";
  return (
    <section className="machine-hardware" aria-label="机器硬件信息">
      <div className="section-title">
        <h3>硬件信息</h3>
        {canEdit && !machine.archived && (
          <button onClick={onRefresh} disabled={collecting}>
            {collecting ? "采集中…" : "更新机器信息"}
          </button>
        )}
      </div>
      <p role="status">
        {statusNames[machine.collection_status || "never"] || "未知"} ·
        最近尝试：{time(machine.last_attempt_at)} · 最近成功：
        {time(machine.last_success_at)}
      </p>
      {machine.collection_error && (
        <p className="error">{machine.collection_error}</p>
      )}
      {machine.ssh_host_trust?.trusted && (
        <p className="muted">
          已信任 SSH 指纹：
          <code>{machine.ssh_host_trust.trusted.fingerprint}</code>
        </p>
      )}
      {machine.ssh_host_trust?.pending && (
        <HostTrustPrompt
          key={machine.ssh_host_trust.pending.challenge_id}
          pending={machine.ssh_host_trust.pending}
          canEdit={canEdit && !machine.archived}
          busy={collecting}
          onTrust={onTrust}
        />
      )}
      {machine.hardware_info && (
        <Snapshot info={machine.hardware_info} title="上次完整采集结果" />
      )}
      {machine.collection_status === "partial" && machine.last_attempt_info && (
        <Snapshot info={machine.last_attempt_info} title="本次部分结果" />
      )}
      {!machine.hardware_info && machine.collection_status !== "partial" && (
        <p className="muted">
          尚无硬件信息，更新后可查看 CPU、内存、磁盘与网卡。
        </p>
      )}
    </section>
  );
}
