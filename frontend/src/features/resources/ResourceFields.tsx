import { firstRdmaPair, rdmaPairs } from "./cacheRdma";
import type { CacheMemberOption } from "./cacheMemberOptions";
import {
  type Parameters,
  type ResourceAction,
  type ResourceField,
  type ResourceMachine,
  type SavedResource,
  newMember,
  stateLabels,
} from "./types";

type Props = {
  action: ResourceAction;
  values: Parameters;
  machines: ResourceMachine[];
  resources: SavedResource[];
  disabled: boolean;
  filesystemOptions?: string[];
  cacheGroupOptions?: string[];
  portPlanning?: boolean;
  cacheMemberDefaults?: Parameters;
  cacheMemberOptions?: CacheMemberOption[];
  onChange: (key: string, value: unknown) => void;
};
export function ResourceFields({
  action,
  values,
  machines,
  resources,
  disabled,
  filesystemOptions,
  cacheGroupOptions,
  portPlanning = false,
  cacheMemberDefaults = {},
  cacheMemberOptions = [],
  onChange,
}: Props) {
  const eligible = machines.filter((machine) => machine.can_manage);
  function input(field: ResourceField) {
    const value = values[field.key];
    if (field.key === "count") return <label>{field.label}<input type="number" min={1} step={1} required disabled={disabled} value={String(value ?? 1)} onChange={e=>onChange(field.key,e.target.value === "" ? "" : Number(e.target.value))}/><small>{action.action === "mount.create" ? `数量大于 1 时生成独立路径，例如 ${String(values.mount_path || "/mnt/client").replace(/\/$/, "")}-001、-002；每个客户端自动检查并分配端口。` : "每份成员配置重复创建指定数量，不设单批数量上限；批量时使用自动端口，成员 ID 请留空。同一缓存组新增多个成员。"} 中途失败保留已完成实例，停止后续步骤。</small></label>;
    if (action.action === "cache.delete" && field.key === "member_id")
      return (
        <label>
          {field.label}
          <select
            required={field.required}
            disabled={disabled || !cacheMemberOptions.length}
            value={String(value || "")}
            onChange={(event) => onChange(field.key, event.target.value)}
          >
            <option value="">请选择缓存组成员</option>
            {cacheMemberOptions.map((member) => (
              <option
                key={member.id}
                value={member.id}
                disabled={!member.selectable}
              >
                {member.groupName} · {member.id} · {member.address} ·{" "}
                {member.stateLabel}
              </option>
            ))}
          </select>
        </label>
      );
    if (action.action === "mount.create" && field.key === "cache_group") {
      const selected = String(value || "");
      const unavailable = Boolean(selected && !cacheGroupOptions?.includes(selected));
      return <div><label>{field.label}<select disabled={disabled} value={selected}
        onChange={event => onChange(field.key, event.target.value)}>
        <option value="">不指定缓存组</option>
        {unavailable && <option value={selected} disabled>{selected}（已失效）</option>}
        {(cacheGroupOptions || []).map(name => <option key={name} value={name}>{name}</option>)}
      </select></label>
        {unavailable && <p role="alert" className="error">所选缓存组不在最新列表中，请刷新列表或重新选择。</p>}
      </div>;
    }
    if (field.key === "fs_name" && filesystemOptions !== undefined)
      return (
        <label>
          {field.label}
          <select
            required
            disabled={disabled || !filesystemOptions.length}
            value={String(value || "")}
            onChange={(event) => onChange(field.key, event.target.value)}
          >
            <option value="">请选择文件系统</option>
            {filesystemOptions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      );
    if (field.type === "members") {
      const members = (Array.isArray(value) ? value : []) as Parameters[];
      return (
        <fieldset className="resource-members" disabled={disabled}>
          <legend>{field.label}</legend>
          {members.map((member, index) => {
            const update = (key: string, next: unknown) =>
              onChange(
                field.key,
                members.map((item, i) =>
                  i === index ? { ...item, [key]: next } : item,
                ),
              );
            const prefix = `成员 ${index + 1}`;
            const machine = machines.find(row => row.id === member.machine_id);
            const pairs = rdmaPairs(machine);
            const devices = [...new Set(pairs.map(pair => pair.device))];
            const currentDevice = String(member.rdma_device || "");
            const validDevice = devices.includes(currentDevice) ? currentDevice : "";
            const ports = pairs.filter(pair => pair.device === validDevice).map(pair => pair.port);
            const currentPort = Number(member.rdma_port);
            const validPort = ports.includes(currentPort) ? currentPort : 0;
            return (
              <fieldset className="resource-member" key={index}>
                <legend>{prefix}</legend>
                <div className="resource-fields">
                  <label>{prefix} ID（留空由平台生成）
                    <input value={String(member.member_id || "")} placeholder="平台自动生成"
                      maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9_.-]*"
                      onChange={e => update("member_id", e.target.value)} />
                  </label>
                  <label>
                    {prefix} 机器
                    <select
                      required
                      value={String(member.machine_id || "")}
                      onChange={(e) => {
                        const machine = eligible.find(
                          (m) => m.id === e.target.value,
                        );
                        onChange(
                          field.key,
                          members.map((item, i) =>
                            i === index
                              ? {
                                  ...item,
                                  machine_id: e.target.value,
                                  ...(item.use_rdma ? firstRdmaPair(machine) : {}),
                                  ...(portPlanning
                                    ? {
                                        listen_ip: machine?.address || "",
                                        target_user: machine?.ssh_user || "",
                                      }
                                    : {}),
                                }
                              : item,
                          ),
                        );
                      }}
                    >
                      <option value="">请选择机器</option>
                      {eligible.map((machine) => (
                        <option key={machine.id} value={machine.id}>
                          {machine.name} · {machine.address} ·{" "}
                          {machine.ssh_user}
                        </option>
                      ))}
                    </select>
                  </label>
                  {portPlanning && (
                    <label>
                      {prefix} 端口分配
                      <select
                        value={String(member.port_mode || "auto")}
                        onChange={(e) => update("port_mode", e.target.value)}
                      >
                        <option value="auto">自动分配（推荐）</option>
                        <option value="manual">手动指定</option>
                      </select>
                    </label>
                  )}
                  {portPlanning && member.port_mode !== "manual" && (
                    <p className="muted">
                      自动从 21000–29999 选择可用端口，无需手动填写。
                    </p>
                  )}
                  {[
                    ["target_user", "执行用户", "text", true],
                    ["listen_ip", "监听 IP", "text", true],
                    ["listen_port", "监听端口", "number", true],
                    ["cache_dir", "缓存目录", "text", true],
                    ["cache_size_mb", "缓存容量 (MB)", "number", true],
                  ]
                    .filter(
                      ([key]) =>
                        key !== "listen_port" ||
                        !portPlanning ||
                        member.port_mode === "manual",
                    )
                    .map(([key, label, type, required]) => (
                      <label key={String(key)}>
                        {prefix} {String(label)}
                        <input
                          type={String(type)}
                          required={Boolean(required)}
                          min={type === "number" ? 1 : undefined}
                          value={String(member[String(key)] ?? "")}
                          onChange={(e) =>
                            update(
                              String(key),
                              type === "number" && e.target.value !== ""
                                ? Number(e.target.value)
                                : e.target.value,
                            )
                          }
                        />
                      </label>
                    ))}
                  <label className="resource-checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(member.use_rdma)}
                      onChange={(e) => onChange(field.key, members.map((item, i) => i === index
                        ? { ...item, use_rdma: e.target.checked,
                            ...(e.target.checked ? firstRdmaPair(machine) : { rdma_device: "", rdma_port: 1 }) }
                        : item))}
                    />
                    {prefix} 使用 RDMA
                  </label>
                  {Boolean(member.use_rdma) && (
                    !member.machine_id ? <p role="alert" className="error">请先选择{prefix}的机器，再选择 RDMA 设备。</p>
                    : !pairs.length ? <p role="alert" className="error">{machine?.rdma === null || machine?.rdma === undefined
                      ? "该机器未采集 RDMA 信息，请先更新机器信息。" : "该机器没有 RDMA 设备，无法使用 RDMA。"}</p>
                    : <>
                      <label>{prefix} RDMA 设备
                        <select required value={validDevice} onChange={e => {
                          const device = e.target.value;
                          const port = pairs.find(pair => pair.device === device)?.port || 1;
                          onChange(field.key, members.map((item, i) => i === index
                            ? { ...item, rdma_device: device, rdma_port: port } : item));
                        }}>
                          <option value="">请选择 RDMA 设备</option>
                          {devices.map(device => <option key={device} value={device}>{device}</option>)}
                        </select>
                      </label>
                      <label>{prefix} RDMA 端口
                        <select required disabled={!validDevice} value={validPort || ""}
                          onChange={e => update("rdma_port", Number(e.target.value))}>
                          <option value="">请选择 RDMA 端口</option>
                          {ports.map(port => <option key={port} value={port}>{port}</option>)}
                        </select>
                      </label>
                      {(!validDevice || !validPort) && <p role="alert" className="error">当前 RDMA 设备或端口不属于所选机器，请重新选择。</p>}
                    </>
                  )}
                </div>
                <button
                  type="button"
                  disabled={members.length <= 1}
                  onClick={() =>
                    onChange(
                      field.key,
                      members.filter((_, i) => i !== index),
                    )
                  }
                >
                  移除{prefix}
                </button>
              </fieldset>
            );
          })}
          <button
            type="button"
            onClick={() =>
              onChange(field.key, [
                ...members,
                { ...newMember(field), ...cacheMemberDefaults, member_id: "" },
              ])
            }
          >
            添加缓存成员
          </button>
          {!eligible.length && (
            <p className="muted">
              没有可管理的机器，请先登记机器或联系管理员。
            </p>
          )}
        </fieldset>
      );
    }
    if (field.key === "machine_id")
      return (
        <label>
          {field.label}
          <select
            required={field.required}
            disabled={disabled}
            value={String(value || "")}
            onChange={(e) => onChange(field.key, e.target.value)}
          >
            <option value="">请选择机器</option>
            {eligible.map((machine) => (
              <option key={machine.id} value={machine.id}>
                {machine.name} · {machine.address} · {machine.ssh_user}
              </option>
            ))}
          </select>
        </label>
      );
    if (field.key === "resource_id") {
      const choices = resources.filter(resource =>
        resource.kind === action.section &&
        resource.state !== "deleted" &&
        resource.state !== "planned" &&
        (action.action !== "mount.unmount" || resource.state === "mounted") &&
        (action.action !== "mount.delete" || resource.state === "unmounted"),
      );
      const selected = String(value || "");
      const unavailable = ["mount.unmount", "mount.delete"].includes(action.action) && !!selected &&
        !choices.some(resource => resource.id === selected);
      return <div>
        <label>
          {action.section === "cache" ? "选择缓存组" : "选择挂载点"}
          <select required={field.required} disabled={disabled} value={unavailable ? "" : selected}
            onChange={e => onChange(field.key, e.target.value)}>
            <option value="">{action.action === "mount.unmount" ? "请选择已挂载的文件系统" : "请选择已保存资源"}</option>
            {choices.map(resource => <option key={resource.id} value={resource.id}>
              {resource.name} · {stateLabels[resource.state] || resource.state}
            </option>)}
          </select>
        </label>
        {unavailable && <p role="alert" className="error">所选挂载点不再是已挂载状态，请重新选择。</p>}
      </div>;
    }
    if (field.type === "boolean")
      return (
        <label className="resource-checkbox">
          <input
            type="checkbox"
            disabled={disabled}
            checked={Boolean(value)}
            onChange={(e) => onChange(field.key, e.target.checked)}
          />
          {field.label}
        </label>
      );
    if (field.key === "lines")
      return (
        <label>
          {field.label}
          <select
            disabled={disabled}
            value={String(value || 500)}
            onChange={(event) =>
              onChange(field.key, Number(event.target.value))
            }
          >
            {[100, 500, 1000].map((lines) => (
              <option key={lines} value={lines}>
                {lines}
              </option>
            ))}
          </select>
        </label>
      );
    if (field.type === "select")
      return (
        <label>
          {field.label}
          <select
            required={field.required}
            disabled={disabled}
            value={String(value ?? "")}
            onChange={(e) => onChange(field.key, e.target.value)}
          >
            {!field.required && <option value="">默认</option>}
            {field.required && value === "" && <option value="">请选择</option>}
            {(field.options || []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      );
    return (
      <label>
        {field.label}
        <input
          type={field.type}
          required={field.required}
          disabled={disabled}
          autoComplete={field.type === "password" ? "new-password" : "off"}
          value={String(value ?? "")}
          placeholder={
            field.key === "filename" ? "留空先查看日志文件列表" : undefined
          }
          pattern={field.key === "filename" ? "[^/\\\\]+" : undefined}
          onChange={(e) =>
            onChange(
              field.key,
              field.type === "number" && e.target.value !== ""
                ? Number(e.target.value)
                : e.target.value,
            )
          }
        />
      </label>
    );
  }
  return (
    <div className="resource-fields">
      {action.fields.map((field) => (
        <div
          className={
            field.type === "members" ? "resource-field-wide" : "resource-field"
          }
          key={field.key}
        >
          {input(field)}
        </div>
      ))}
    </div>
  );
}
