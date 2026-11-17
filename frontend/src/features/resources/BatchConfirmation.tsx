import { useEffect, useRef } from "react";
import { cacheMemberOptions } from "./cacheMemberOptions";
import {
  stateLabels,
  type Parameters,
  type ResourceAction,
  type ResourceSnapshot,
} from "./types";
export type Confirmation = {
  action: ResourceAction;
  values: Parameters;
  snapshot: ResourceSnapshot;
};
export function BatchConfirmation({
  request,
  cluster,
  onResolve,
}: {
  request: Confirmation;
  cluster: string;
  onResolve: (approved: boolean) => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    cancel.current?.focus();
    return () => before?.focus();
  }, []);
  const { action, values, snapshot } = request;
  const key = ["member_ids", "resource_ids", "fs_names"].find((k) =>
    Array.isArray(values[k]),
  )!;
  const ids = values[key] as string[];
  let members: ReturnType<typeof cacheMemberOptions> = [];
  try {
    const list = snapshot.operations.find((o) => o.action === "cache.list");
    if (list) members = cacheMemberOptions(list);
  } catch {
    /* Preserve explicit unknown state. */
  }
  const rows = ids.map((id) => {
    const resource = snapshot.resources.find((r) => r.id === id);
    const member = members.find((m) => m.id === id);
    const machine = snapshot.machines.find(
      (m) => m.id === resource?.data.machine_id,
    );
    return {
      id,
      name: resource?.name || member?.groupName || id,
      machine: machine
        ? `${machine.name} · ${machine.address}`
        : member?.address || "—",
      state: resource
        ? stateLabels[resource.state] || resource.state
        : member?.stateLabel || "以集群执行时检查为准",
    };
  });
  return (
    <div className="resource-confirm-backdrop">
      <section
        className="resource-confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resource-confirm-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") onResolve(false);
          if (e.key === "Tab") {
            const buttons = Array.from(
              e.currentTarget.querySelectorAll<HTMLButtonElement>(
                "button:not([disabled])",
              ),
            );
            const first = buttons[0],
              last = buttons[buttons.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <h2 id="resource-confirm-title">确认批量操作</h2>
        <p>
          集群：<strong>{cluster}</strong>
        </p>
        <p>{action.label}</p>
        <p>
          本次将操作以下 <strong>{ids.length}</strong>{" "}
          项，名单包含此前勾选但当前筛选未显示的项目。
        </p>
        {values.force === true && (
          <p className="error">
            强制停止使用 SIGKILL（kill -9），不会执行进程退出清理。
          </p>
        )}
        <div className="resource-confirm-targets">
          <table>
            <thead>
              <tr>
                <th>名称 / 目标</th>
                <th>机器 / 地址</th>
                <th>最近状态</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.name}
                    {row.name !== row.id && <small>{row.id}</small>}
                  </td>
                  <td>{row.machine}</td>
                  <td>{row.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="resource-confirm-actions">
          <button ref={cancel} onClick={() => onResolve(false)}>
            取消
          </button>
          <button className="primary" onClick={() => onResolve(true)}>
            确认执行 {ids.length} 项
          </button>
        </div>
      </section>
    </div>
  );
}
