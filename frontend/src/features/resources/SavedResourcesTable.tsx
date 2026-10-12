import { CacheMemberManagementButtons } from "./CacheMemberManagementButtons";
import { LazyDetails } from "./LazyDetails";
import { Fragment, useState } from "react";
import { StructuredResult } from "./ResourceOperationView";
import {
  stateLabels,
  type ResourceAction,
  type ResourceMachine,
  type SavedResource,
} from "./types";

const shortcuts = {
  cache: [
    ["cache.stop", "平滑停止"],
    ["cache.force_stop", "强制停止"],
    ["cache.delete", "删除"],
  ],
  mount: [
    ["mount.status", "状态"],
    ["mount.unmount", "卸载"],
    ["mount.logs", "日志"],
  ],
};

export function SavedResourcesTable({
  resources,
  machines,
  actions,
  disabled,
  onAction,
  queried = false,
  onMemberAction,
}: {
  queried?: boolean;
  onMemberAction?: (
    resource: SavedResource,
    action: string,
    memberId: string,
  ) => void;
  resources: SavedResource[];
  machines: ResourceMachine[];
  actions: ResourceAction[];
  disabled: boolean;
  onAction: (resource: SavedResource, action: string) => void;
}) {
  const labelState = (value: string) =>
    (queried
      ? (
          {
            running: "在线",
            partial: "部分在线",
            unknown: "状态未知",
          } as Record<string, string>
        )[value]
      : undefined) ||
    stateLabels[value] ||
    value;
  const [expanded, setExpanded] = useState(new Set<string>());
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const machineNames = new Map(
    machines.map((machine) => [machine.id, machine.name]),
  );
  const machineName = (resource: SavedResource) => {
    const id = String(resource.data.machine_id ?? "");
    return machineNames.get(id) || id;
  };
  const states = [...new Set(resources.map((resource) => resource.state))];
  const selectedState = states.includes(state) ? state : "";
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = resources.filter((resource) => {
    const searchable = [
      resource.name,
      resource.data.fs_name,
      resource.data.mount_path,
      machineName(resource),
    ]
      .join(" ")
      .toLocaleLowerCase();
    return (
      (!selectedState || resource.state === selectedState) &&
      searchable.includes(normalizedQuery)
    );
  });
  const hasCache = resources.some((resource) => resource.kind === "cache");
  const hasMount = resources.some((resource) => resource.kind === "mount");

  if (!resources.length)
    return (
      <p className="muted resource-inventory-empty">
        {queried ? "查询未返回缓存组。" : "暂无保存的资源记录。"}
      </p>
    );

  return (
    <div className="resource-inventory">
      <div className="resource-inventory-toolbar">
        <label>
          搜索资源
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="名称、文件系统、机器或挂载路径"
          />
        </label>
        <span className="muted resource-inventory-count" role="status">
          显示 {filtered.length} / {resources.length} 条
        </span>
      </div>
      {!filtered.length ? (
        <p className="muted resource-inventory-empty">没有匹配的资源。</p>
      ) : (
        <div className="resource-table-scroll">
          <table
            className="resource-inventory-table"
            aria-label={queried ? "缓存组列表" : "已保存资源"}
          >
            <thead>
              <tr>
                <th scope="col">资源名称</th>
                <th scope="col">
                  状态
                  <select
                    className="resource-state-filter"
                    aria-label="筛选资源状态"
                    value={selectedState}
                    onChange={(event) => setState(event.target.value)}
                  >
                    <option value="">全部状态</option>
                    {states.map((value) => (
                      <option key={value} value={value}>{labelState(value)}</option>
                    ))}
                  </select>
                </th>
                {hasCache && <th scope="col">成员数</th>}
                {hasCache && <th scope="col">总容量（GiB）</th>}
                {hasCache && queried && (
                  <>
                    <th>在线数</th>
                    <th>离线数</th>
                  </>
                )}
                {hasMount && (
                  <>
                    <th scope="col">文件系统</th>
                    <th scope="col">机器</th>
                    <th scope="col">挂载路径</th>
                  </>
                )}
                <th scope="col">操作</th>
                <th scope="col">详情</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((resource) => (
                <Fragment key={resource.id}>
                  <tr>
                    <th scope="row">{resource.name}</th>
                    <td>
                      <span className={`badge resource-state-${resource.state}`}>
                        {labelState(resource.state)}
                      </span>
                    </td>
                    {hasCache && (
                      <td>
                        {resource.kind === "cache" &&
                        Array.isArray(resource.data.members)
                          ? resource.data.members.length
                          : "—"}
                      </td>
                    )}
                    {hasCache && <td>{cacheCapacityGiB(resource)}</td>}
                    {hasCache && queried && (
                      <>
                        <td>{String(resource.data.online_count ?? 0)}</td>
                        <td>{String(resource.data.offline_count ?? 0)}</td>
                      </>
                    )}
                    {hasMount && (
                      <>
                        <td>
                          {resource.kind === "mount"
                            ? String(resource.data.fs_name || "—")
                            : "—"}
                        </td>
                        <td>
                          {resource.kind === "mount"
                            ? machineName(resource) || "—"
                            : "—"}
                        </td>
                        <td className="resource-inventory-path">
                          {resource.kind === "mount"
                            ? String(resource.data.mount_path || "—")
                            : "—"}
                        </td>
                      </>
                    )}
                    <td>
                      <div className="resource-inventory-actions">
                        {queried &&
                          resource.kind === "cache" &&
                          actions.some((a) => a.action === "cache.create") && (
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() => onAction(resource, "cache.create")}
                            >
                              添加成员
                            </button>
                          )}
                        {shortcuts[resource.kind]
                          .filter(([key]) =>
                            actions.some((action) => action.action === (key === "cache.force_stop" ? "cache.stop" : key)),
                          )
                          .map(([key, label]) => (
                            <button
                              key={key}
                              type="button"
                              disabled={
                                disabled ||
                                (key === "mount.unmount" && resource.state !== "mounted") ||
                                (queried &&
                                  ["cache.stop", "cache.force_stop"].includes(key) &&
                                  !resource.data.can_stop)
                              }
                              title={
                                queried &&
                                ["cache.stop", "cache.force_stop"].includes(key) &&
                                !resource.data.can_stop
                                  ? String(
                                      resource.data.stop_reason ||
                                        "请展开成员信息核实执行机器",
                                    )
                                  : undefined
                              }
                              aria-label={`${label} ${resource.name}`}
                              onClick={() => {
                                if (!disabled && !(key === "mount.unmount" && resource.state !== "mounted")) onAction(resource, key);
                              }}
                            >
                              {queried && resource.kind === "cache"
                                ? `${label}全部成员`
                                : label}
                            </button>
                          ))}
                      </div>
                    </td>
                    <td>
                      {queried ? (
                        <button
                          type="button"
                          aria-expanded={expanded.has(resource.id)}
                          onClick={() =>
                            setExpanded((previous) => {
                              const next = new Set(previous);
                              if (next.has(resource.id))
                                next.delete(resource.id);
                              else next.add(resource.id);
                              return next;
                            })
                          }
                        >
                          成员信息
                        </button>
                      ) : (
                        <LazyDetails
                          className="resource-inventory-details"
                          summary="保存的资源信息"
                        >
                          <StructuredResult value={resource.data} />
                          <small>登记时间：{resource.created_at}</small>
                        </LazyDetails>
                      )}
                    </td>
                  </tr>
                  {queried &&
                    expanded.has(resource.id) &&
                    Array.isArray(resource.data.members) && (
                      <tr className="cache-members-row">
                        <td
                          colSpan={4 + (hasCache ? (queried ? 4 : 2) : 0) + (hasMount ? 3 : 0)}
                        >
                          <table aria-label={`${resource.name} 成员列表`}>
                            <thead>
                              <tr>
                                <th>成员 UUID</th>
                                <th>机器 / 地址</th>
                                <th>执行用户</th>
                                <th>缓存容量</th>
                                <th>权重</th>
                                <th>状态</th>
                                <th>成员操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {resource.data.members.map((member) => (
                                <tr key={member.member_id}>
                                  <td>
                                    <code>{member.member_id}</code>
                                  </td>
                                  <td>
                                    {machineNames.get(
                                      String(member.machine_id),
                                    ) || ""}{" "}
                                    {member.address}
                                  </td>
                                  <td>{member.target_user || "—"}</td>
                                  <td>{member.cache_size_mb != null ? `${member.cache_size_mb} MiB（${member.capacity_source}）` : "未获取"}</td>
                                  <td>{member.weight ?? "未获取"}</td>
                                  <td>{member.state}</td>
                                  <td>
                                    <button
                                      type="button"
                                      aria-label={`停止成员 ${member.member_id}`}
                                      disabled={
                                        disabled ||
                                        !member.can_stop ||
                                        member.state === "离线" ||
                                        !actions.some(
                                          (a) => a.action === "cache.stop",
                                        )
                                      }
                                      onClick={() =>
                                        onMemberAction?.(
                                          resource,
                                          "cache.stop",
                                          member.member_id,
                                        )
                                      }
                                    >
                                      平滑停止
                                    </button>
                                    <button
                                      type="button"
                                      aria-label={`删除成员 ${member.member_id}`}
                                      disabled={
                                        disabled ||
                                        !member.selectable ||
                                        !actions.some(
                                          (a) => a.action === "cache.delete",
                                        )
                                      }
                                      onClick={() =>
                                        onMemberAction?.(
                                          resource,
                                          "cache.delete",
                                          member.member_id,
                                        )
                                      }
                                    >
                                      删除
                                    </button>
                                    <button type="button" aria-label={`强制停止成员 ${member.member_id}`}
                                      disabled={disabled || !member.can_stop || member.state === "离线" || !actions.some(a => a.action === "cache.stop")}
                                      onClick={() => onMemberAction?.(resource, "cache.force_stop", String(member.member_id))}>强制停止</button>
                                    <CacheMemberManagementButtons memberId={String(member.member_id)} grouped actions={actions} disabled={disabled}
                                      onAction={key => onMemberAction?.(resource, key, String(member.member_id))} />
                                    {!member.can_stop && (
                                      <small>
                                        {String(
                                          member.stop_reason ||
                                            "无法确定执行机器，请刷新列表",
                                        )}
                                      </small>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {!resource.data.can_stop && (
                            <p className="muted">
                              {String(
                                resource.data.stop_reason ||
                                  "部分成员无法定位执行机器，请刷新列表并检查机器资源。",
                              )}
                            </p>
                          )}
                          <small>查询时间：{resource.created_at}</small>
                        </td>
                      </tr>
                    )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function cacheCapacityGiB(resource: SavedResource): string {
  if (resource.kind !== "cache" || !Array.isArray(resource.data.members)) return "未获取";
  let total = 0;
  let missing = 0;
  for (const member of resource.data.members) {
    const size = member.cache_size_mb;
    if (typeof size === "number" && Number.isFinite(size) && size >= 0) total += size;
    else missing++;
  }
  if (missing === resource.data.members.length && missing > 0) return "未获取";
  const value = (total / 1024).toLocaleString("zh-CN", {maximumFractionDigits: 3});
  return missing ? `${value}（已知容量，${missing} 个成员未获取）` : value;
}
