import { useState } from "react";
import type { GuidedMetadata, Profile } from "./types";

const fieldLabels:Record<string,string> = {
  dingo:'Dingo',mds_client:'MDS 客户端',client_binaries:'客户端二进制',cache_binaries:'缓存二进制',chaos_tool:'故障工具',
  mounts:'挂载目录',client_cache:'客户端缓存目录',client_logs:'客户端日志目录',remote_cache:'远端缓存目录',
};
function summaryValue(value:unknown):string {
  if (typeof value === 'string') return value || '未知';
  if (Array.isArray(value)) return value.length ? value.map(summaryValue).join('、') : '未知';
  return '未知';
}
function SummaryFields({values}:{values:Record<string,unknown>}) {
  return <>{Object.entries(values).map(([key,value]) => <p key={key}>{fieldLabels[key] || key}：{summaryValue(value)}</p>)}</>;
}

function registeredTarget(metadata:GuidedMetadata, host:string) {
  return metadata.machines?.find(machine =>
    machine.name === host || machine.address === host || machine.aliases.includes(host));
}

export function environmentReason(profile:Profile, clusterId:string, metadata:GuidedMetadata) {
  if (profile.source_kind !== "predefined") return "此引导只使用已有预置环境";
  if (!profile.enabled || profile.validation === "template" || profile.display?.template)
    return profile.display?.issue || "基础模板或配置不完整";
  if (profile.display?.issue) return profile.display.issue;
  const cluster = metadata.clusters.find(item => item.id === clusterId);
  if (!cluster) return "请先选择集群";
  if (!cluster.available) return "集群管理机器不可用";
  const addresses = profile.display?.descriptor?.mds_addresses || profile.display?.mds_addresses || [];
  if (!addresses.length || addresses.slice().sort().join(",") !== cluster.mds_addresses.slice().sort().join(","))
    return "环境目标与所选集群不一致";
  if (metadata.machines && profile.display?.descriptor?.targets.some(target => {
    const machine = registeredTarget(metadata,target.host);
    return !machine || !machine.available || machine.ssh_user !== target.user;
  })) return "执行目标未登记、无管理权限或 SSH 用户不匹配";
  return "";
}

export function EnvironmentStep({metadata,profiles,clusterId,environmentId,onCluster,onEnvironment,onRefresh}:{
  metadata:GuidedMetadata;profiles:Profile[];clusterId:string;environmentId:string;
  onCluster:(value:string)=>void;onEnvironment:(value:string)=>void;onRefresh:()=>void;
}) {
  const [query,setQuery] = useState("");
  const profile = profiles.find(item => item.id === environmentId);
  const cluster = metadata.clusters.find(item => item.id === clusterId);
  const descriptor = profile?.display?.descriptor;
  return <section className="functional-card">
    <h1>选择测试环境</h1>
    <p>选择已登记的集群和工程中的测试环境。执行位置以环境及集群登记信息为准。</p>
    <div className="functional-form">
      <label>目标集群
        <select value={clusterId} onChange={event => onCluster(event.target.value)}>
          <option value="">选择集群</option>
          {metadata.clusters.map(item => <option key={item.id} value={item.id}>
            {item.name} · {item.management_machine.name}（{item.management_machine.address}）· {item.management_machine.ssh_user}
          </option>)}
        </select>
      </label>
      <label>搜索测试环境
        <input type="search" value={query} onChange={event => setQuery(event.target.value)}
          placeholder="输入环境名或源文件" />
      </label>
      <label>测试环境
        <select value={environmentId} onChange={event => onEnvironment(event.target.value)}>
          <option value="">选择测试环境</option>
          {profiles.filter(item => `${item.name} ${item.source_file || ""}`.toLowerCase().includes(query.toLowerCase()))
            .map(item => {
              const reason = environmentReason(item,clusterId,metadata);
              const hosts = item.display?.descriptor?.targets?.map(target => {
                const machine = registeredTarget(metadata,target.host);
                return machine ? `${machine.name}（${machine.address}）` : target.host;
              }).filter(Boolean).join("、");
              return <option key={item.id} value={item.id} disabled={!!reason}>
                {item.name} · {hosts || "测试机器按用例决定"}{reason ? ` · ${reason}` : ""}
              </option>;
            })}
        </select>
      </label>
    </div>
    <div className="functional-actions">
      <button type="button" onClick={onRefresh}>刷新环境列表</button>
      <details><summary>查看环境要求</summary><p>需为已登记机器配置管理权限和 SSH 用户；环境源、目标集群及所选用例必须匹配。检查环境会再次验证运行时和远端状态。</p></details>
    </div>
    {cluster && <div className="functional-target"><strong>控制机</strong><p>
      {cluster.management_machine.name} · {cluster.management_machine.address} · SSH 用户 {cluster.management_machine.ssh_user}
    </p><small>控制机负责启动 DTT；实际客户端和缓存机器以环境为准。</small></div>}
    {profile && descriptor && <div className="functional-target">
      <strong>环境摘要：{profile.name}</strong>
      <p>源文件：{profile.source_file || "未知"} · 继承：{profile.display?.base || "无"}</p>
      <p>MDS：{descriptor.mds_addresses.join("、") || "未配置"} · 存储：{descriptor.storage_type || "按环境配置"}</p>
      <p>客户端：{descriptor.client_count ?? "按用例决定"} · 缓存节点：{descriptor.cache_count ?? "按用例决定"}</p>
      <p>执行目标：{descriptor.targets.map(item => {
        const machine = registeredTarget(metadata,item.host);
        return machine ? `${machine.name}（${machine.address}，${item.user}，${item.role}）`
          : `${item.host}（${item.user}，${item.role}；未登记或无权限）`;
      }).join("、") || "按用例决定"}</p>
      <p>文件系统命名：按模块环境约定</p>
      <strong>程序</strong><SummaryFields values={descriptor.programs}/>
      <strong>目录</strong><SummaryFields values={descriptor.directories}/>
    </div>}
  </section>;
}
