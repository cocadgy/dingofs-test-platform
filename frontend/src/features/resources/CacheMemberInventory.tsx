import { CacheMemberManagementButtons } from "./CacheMemberManagementButtons";
import type { ResourceAction, SavedResource } from "./types";
import { useState } from "react";
import type { CacheMemberOption } from "./cacheMemberOptions";

export function CacheMemberInventory({ members, disabled = false, onDelete, onDeleteUngrouped, actions = [], onManage, resources = [] }: {
  members: CacheMemberOption[];
  resources?: SavedResource[];
  actions?: ResourceAction[];
  onManage?: (member: CacheMemberOption, action: string) => void;
  disabled?: boolean;
  onDelete?: (member: CacheMemberOption) => void;
  onDeleteUngrouped?: () => void;
}) {
  const [search, setSearch] = useState("");
  const [ungrouped, setUngrouped] = useState(false);
  const needle = search.trim().toLowerCase();
  const rows = members.filter(member =>
    (!ungrouped || !member.groupName) &&
    [member.id, member.groupName || "未分组", member.address, member.stateLabel]
      .some(value => value.toLowerCase().includes(needle)),
  );
  const capacities = new Map<string, unknown>();
  for (const resource of resources) {
    if (resource.kind !== "cache" || ["deleted", "planned", "failed"].includes(resource.state)) continue;
    if (!Array.isArray(resource.data.members)) continue;
    for (const member of resource.data.members) {
      if (member.cache_size_mb != null) capacities.set(member.member_id, member.cache_size_mb);
    }
  }
  function capacity(member: CacheMemberOption) {
    if (member.cacheSizeMb != null) return `${member.cacheSizeMb} MiB（成员查询）`;
    const saved = capacities.get(member.id);
    return saved != null ? `${saved} MiB（平台配置）` : "未获取";
  }
  return <section className="resource-inventory" aria-label="全部缓存成员">
    <h4>缓存成员列表</h4>
    <p className="muted">共 {members.length} 个成员，其中 {members.filter(member => !member.groupName).length} 个未分组。成员列表独立于缓存组列表。</p>
    <div className="resource-inventory-toolbar">
      <label>搜索成员<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="成员 ID、组名、地址或状态" /></label>
      <label>成员范围<select value={ungrouped ? "ungrouped" : "all"} onChange={event => setUngrouped(event.target.value === "ungrouped")}>
        <option value="all">全部成员</option><option value="ungrouped">仅未分组成员</option>
      </select></label>
    </div>
    <div className="resource-inventory-actions">
      <button type="button" disabled={disabled || !onDeleteUngrouped || !members.some(member => !member.groupName && member.selectable)}
        onClick={onDeleteUngrouped}>删除所有未分组成员</button>
    </div>
    <p className="muted">按完整成员列表删除，不受搜索筛选影响；在线成员跳过，每批最多 100 个。</p>
    <div className="resource-table-scroll"><table className="resource-inventory-table" aria-label="缓存成员列表">
      <thead><tr><th>成员 UUID</th><th>所属缓存组</th><th>机器 / 地址</th><th>缓存容量</th><th>权重</th><th>状态</th><th>成员操作</th></tr></thead>
      <tbody>{rows.map(member => <tr key={member.id}>
        <td><code>{member.id}</code></td><td>{member.groupName || "未分组"}</td><td>{member.address}</td><td>{capacity(member)}</td><td>{member.weight ?? "未获取"}</td><td>{member.stateLabel}</td>
        <td>{!member.groupName ? <button type="button" aria-label={`删除成员 ${member.id}`}
          disabled={disabled || !member.selectable || !onDelete}
          title={!member.selectable ? "请先停止成员，待离线后刷新列表再删除" : "删除成员登记，保留缓存数据"}
          onClick={() => onDelete?.(member)}>删除</button> : "请在缓存组成员列表操作"}
          {!member.groupName && <CacheMemberManagementButtons memberId={member.id} grouped={false} actions={actions} disabled={disabled} onAction={key => onManage?.(member, key)} />}
        </td>
      </tr>)}</tbody>
    </table></div>
    {!rows.length && <p>{members.length ? "没有符合筛选条件的成员。" : "当前没有缓存成员。"}</p>}
  </section>;
}
