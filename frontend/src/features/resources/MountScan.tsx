import { useState } from "react";
import type { ResourceOperation, ResourceSnapshot, MountScanData } from "./types";
import type { Execute } from "./useResourceWorkspace";
import { pendingStates, stateLabels } from "./types";
import "./mount-scan.css";

export function MountScan({ clusterId, snapshot, operations, execute, disabled, error }: {
  clusterId: string; snapshot: ResourceSnapshot; operations: ResourceOperation[];
  execute: Execute; disabled: boolean; error?: string;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const action = snapshot.catalog.find((a) => a.action === "mount.scan");
  const unmountAction = snapshot.catalog.find((a) => a.action === "mount.unmount");
  const machines = snapshot.machines.filter((m) => m.can_manage && m.has_ssh_password);
  const validIds = selected.filter((id) => machines.some((m) => m.id === id));
  const operation = operations.find((op) => op.action === "mount.scan" && op.cluster_id === clusterId);
  return <section className="mount-scan" aria-label="扫描已有挂载">
    <h3>扫描已有挂载</h3>
    <p>扫描已有挂载并保存当前集群的客户端记录，手动挂载的客户端也可在下方管理。容器中的独立挂载可能不可见。</p>
    <fieldset disabled={disabled}>
      <legend>选择扫描机器（最多 20 台）</legend>
      <div className="mount-scan-machines">
        {machines.map((m) => <label key={m.id} className="mount-scan-machine">
          <input type="checkbox" checked={validIds.includes(m.id)}
            disabled={!validIds.includes(m.id) && validIds.length >= 20}
            onChange={(e) => setSelected(e.target.checked ? [...validIds, m.id] : validIds.filter((id) => id !== m.id))} />
          <span className="mount-scan-machine-details">
            <strong>{m.name}（{m.address}）</strong>
            <span>SSH 用户：{m.ssh_user}</span>
          </span>
        </label>)}
      </div>
      {!machines.length && <p>暂无可扫描机器，请先配置机器 SSH 密码并确认管理权限。</p>}
    </fieldset>
    <p>使用 root 核验客户端，必要时会提示 sudo 认证。非正常退出留下的挂载可在扫描结果中点击“卸载残留挂载”。</p>
    <button type="button" disabled={disabled || !action || !validIds.length}
      onClick={() => action && void execute(action, {machine_ids:validIds})}>扫描已有挂载</button>
    {error && <p role="alert" className="error">{error}</p>}
    {operation && <div className="mount-scan-results">
      <h4>最近扫描 · {stateLabels[operation.state] || operation.state}</h4>
      {pendingStates.includes(operation.state) && <p role="status">扫描进行中；需要认证时，请在下方任务记录中完成认证。</p>}
      {operation.state === "failed" && <p role="alert">本次扫描存在失败，以下保留已完成机器的结果；请查看各步骤错误。</p>}
      {operation.message && !operation.result?.steps?.length && <p role="alert">{operation.message}</p>}
      {(operation.result?.steps || []).map((step, index) => {
        const data = step.data as MountScanData | undefined;
        const rows = Array.isArray(data?.mounts) ? data.mounts : undefined;
        return <article key={`${step.machine_id || index}-${index}`} className="mount-scan-host">
          <h4>步骤 {index + 1} · {step.machine_name || "未记录"}（{step.machine_address || "IP 未记录"}）</h4>
          <p>扫描用户：{step.target_user || "未记录"}{data?.scanned_at ? ` · 扫描时间：${data.scanned_at}` : ""}</p>
          {step.failed ? <p role="alert" className="error">{step.message || "扫描失败，请查看任务记录"}</p> : <>
            {data?.warnings?.map((w, i) => <p className="error" key={i}>{w}</p>)}
            {rows?.length === 0 && <p>当前可见命名空间未发现 DingoFS 挂载。</p>}
            {!rows && <p role="alert">未返回有效扫描结果，请查看任务记录。</p>}
            {!!rows?.length && <div className="mount-scan-table"><table>
              <thead><tr>{["文件系统 / 挂载路径", "客户端用户 / PID", "MDS 地址", "集群归属", "平台记录", "操作"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>{rows.map((row) => <tr key={row.mount_id}>
                <td><strong>{row.fs_name || "未识别"}</strong><div>{row.mount_path}</div></td>
                <td>{row.client_user || "无法确认"}<div>PID：{row.pid ?? "未识别"}</div></td>
                <td>{row.mds_addresses.length ? row.mds_addresses.map((a) => <div key={a}>{a}</div>) : "未识别"}</td>
                <td>{({current:"当前集群",other:"其他集群",unknown:"无法确认"})[row.cluster_match]}<div className="muted">{row.reason}</div></td>
                <td>{row.saved_resource_id ? "已保存为平台记录" : "未保存（请查看归属原因）"}</td>
                <td>{row.cleanup_allowed && step.machine_id && unmountAction ? (
                  operations.some(op => op.action === "mount.unmount" && op.state === "succeeded"
                    && op.payload?.scan_operation_id === operation.id && op.payload?.machine_id === step.machine_id
                    && op.payload?.mount_id === row.mount_id) ? <span>已卸载</span> :
                  <button type="button" disabled={disabled}
                    onClick={() => void execute({ ...unmountAction,
                      label: `卸载残留挂载：${step.machine_name}（${step.machine_address}） ${row.mount_path}` },
                      { scan_operation_id: operation.id, machine_id: step.machine_id, mount_id: row.mount_id })}>
                    卸载残留挂载
                  </button>
                ) : "—"}</td>
              </tr>)}</tbody>
            </table></div>}
          </>}
        </article>;
      })}
    </div>}
  </section>;
}
