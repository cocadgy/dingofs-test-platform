import type { ResourceMachine, ResourceOperation } from "./types";
export type PlannedMember = {
  machine_id: string;
  target_user: string;
  listen_ip: string;
  listen_port: number;
  cache_dir: string;
  cache_size_mb: number;
};
export function plannedMembers(operation?: ResourceOperation): PlannedMember[] {
  return (operation?.result?.steps || []).flatMap((step) => {
    const data = step.data as { member?: PlannedMember } | undefined;
    return data?.member ? [data.member] : [];
  });
}
export function CachePortPlan({
  operation,
  machines,
}: {
  operation: ResourceOperation;
  machines: ResourceMachine[];
}) {
  const members = plannedMembers(operation);
  return (
    <section>
      <h4>缓存成员端口检查清单</h4>
      <p>端口检查通过，正在自动提交创建。</p>
      <div className="resource-table-wrap">
        <table aria-label="缓存成员端口检查清单">
          <thead>
            <tr>
              {[
                "机器",
                "执行用户",
                "监听 IP",
                "分配端口",
                "缓存目录",
                "容量（MiB）",
              ].map((title) => (
                <th key={title}>{title}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map((member, i) => (
              <tr key={i}>
                <td>
                  {machines.find((m) => m.id === member.machine_id)?.name ||
                    member.machine_id}
                </td>
                <td>{member.target_user}</td>
                <td>{member.listen_ip}</td>
                <td>{member.listen_port}</td>
                <td>{member.cache_dir}</td>
                <td>{member.cache_size_mb}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        启动前会再次检查。自动模式若端口被抢占，会改用可用端口并在操作结果中显示；手动模式不会自动换端口。
      </p>
    </section>
  );
}
