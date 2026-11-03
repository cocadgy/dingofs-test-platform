import { cacheRdmaReady, rdmaPairs } from "../resources/cacheRdma";
import type { ResourceMachine } from "../resources/types";
import type { CacheDraft, CacheMachineDraft } from "./guidedCacheModel";

export function guidedRdmaError(draft: CacheDraft, machines: ResourceMachine[]) {
  return cacheRdmaReady(draft.rows.map(row => ({ machine_id: row.machineId, use_rdma: row.rdma,
    rdma_device: row.rdmaDevice, rdma_port: row.rdmaPort })), machines)
    ? "" : "RDMA 设备或端口不属于当前机器，请更新机器信息后重新选择。";
}
export function GuidedRdmaFields({ machine, row, onChange }: {
  machine?: ResourceMachine; row: CacheMachineDraft; onChange: (patch: Partial<CacheMachineDraft>) => void;
}) {
  const pairs = rdmaPairs(machine);
  const devices = [...new Set(pairs.map(pair => pair.device))];
  const device = devices.includes(row.rdmaDevice) ? row.rdmaDevice : "";
  const ports = [...new Set(pairs.filter(pair => pair.device === device).map(pair => pair.port))];
  const port = ports.includes(row.rdmaPort) ? row.rdmaPort : "";
  if (!pairs.length) return <p role="alert" className="error">{machine?.rdma == null
    ? "该机器未采集 RDMA 信息，请先更新机器信息。"
    : "该机器没有 RDMA 设备，无法使用 RDMA。"}</p>;
  return <>
    <label>RDMA 设备<select value={device} onChange={e => onChange({ rdmaDevice: e.target.value,
      rdmaPort: pairs.find(pair => pair.device === e.target.value)?.port || 1 })}>
      <option value="">请选择 RDMA 设备</option>{devices.map(name => <option key={name}>{name}</option>)}
    </select></label>
    <label>RDMA 端口<select value={port} disabled={!device} onChange={e => onChange({ rdmaPort: Number(e.target.value) })}>
      <option value="">请选择 RDMA 端口</option>{ports.map(value => <option key={value} value={value}>{value}</option>)}
    </select></label>
    {(!device || !port) && <p role="alert" className="error">请选择当前机器的 RDMA 设备和端口；模板或草稿中的旧配置不会自动替换。</p>}
  </>;
}
