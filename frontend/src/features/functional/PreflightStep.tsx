import { useEffect, useState } from "react";
import { moduleLabels, type GuidedCompatibility, type GuidedConfiguration, type GuidedMetadata,
  type GuidedPreflight, type Profile } from "./types";

export function PreflightStep({configuration,profiles,metadata,compatibility,preflight,busy,
  onCheck,onInstall,onStart}:{
  configuration:GuidedConfiguration;profiles:Profile[];metadata:GuidedMetadata;
  compatibility:GuidedCompatibility|null;preflight:GuidedPreflight|null;busy:boolean;
  onCheck:()=>void;onInstall:()=>void;onStart:(confirmed:string[])=>void;
}) {
  const [accepted,setAccepted] = useState(false);
  const [faultAccepted,setFaultAccepted] = useState(false);
  useEffect(() => { setAccepted(false);setFaultAccepted(false); },[preflight]);
  const cluster = metadata.clusters.find(item => item.id === configuration.cluster_id);
  const fault = configuration.module_plans.some(plan => plan.module === "fault");
  const confirmations = preflight?.required_confirmations || [];
  const allConfirmed = (!confirmations.length || accepted) && (!fault || faultAccepted);
  const installRequired = preflight?.checks.some(item => item.code === "runtime_install_required");
  return <section className="functional-card">
    <h1>检查并启动</h1>
    <p>先运行只读预检，再确认影响范围后启动。预检通过不保证实际创建资源一定成功。</p>
    <div className="functional-target">
      <strong>目标集群与控制机</strong>
      <p>{cluster?.name || "未选择"} · {cluster?.management_machine.name || "未知"}（{cluster?.management_machine.address || "未知"}） · SSH 用户 {cluster?.management_machine.ssh_user || "未知"}</p>
    </div>
    {configuration.module_plans.map(plan => {
      const profile = profiles.find(item => item.id === plan.environment_profile_id);
      const result = compatibility?.modules[plan.module];
      return <div className="functional-target" key={plan.module}>
        <strong>{moduleLabels[plan.module] || plan.module} · {plan.cases.length} 个用例</strong>
        <p>环境：{profile?.name || "未选择"} · 版本 {plan.environment_profile_revision}</p>
        <p>执行目标：{result?.targets?.map(target =>
          `${"name" in target ? target.name : target.host}（${"address" in target ? target.address : target.host}，${target.user}）`).join("、") || "以只读预检结果为准"}</p>
        <p>资源：{profile?.display?.descriptor?.modules?.[plan.module]?.fixed_resources?.join("、") || "按环境与模块约定创建或复用"}</p>
        {result?.impacts?.map((impact,index) => <p key={index}>影响：{impact}</p>)}
      </div>;
    })}
    <p>普通套件成功后清理，失败默认保留现场；专用模块按其恢复规则执行。平台锁不覆盖外部 Jenkins 或人工操作。</p>
    <div className="functional-actions"><button type="button" onClick={onCheck} disabled={busy}>检查环境</button>
      {installRequired && <button type="button" onClick={onInstall} disabled={busy}>确认安装或更新 DTT</button>}
    </div>
    {preflight && <div className="functional-target">
      <strong>{preflight.can_start ? "预检通过" : "预检未通过"}</strong>
      {preflight.checks.map((check,index) => <p key={index}>
        {check.ok ? "通过" : "未通过"} · {check.code}
        {check.host ? ` · ${check.host}` : ""}{check.user ? ` · ${check.user}` : ""}
        {check.conflicts?.map(item => ` · ${item.key}：${item.reason}`).join("")}
      </p>)}
      {preflight.impacts.map((impact,index) => <p key={index}>{impact.description}</p>)}
      {confirmations.length > 0 && <label className="functional-check">
        <input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} />
        我已阅读并确认以上影响范围
      </label>}
      {fault && <label className="functional-check"><input type="checkbox" checked={faultAccepted}
        onChange={event => setFaultAccepted(event.target.checked)} />
        我确认故障用例可能影响所选集群和服务，并已核实恢复规则
      </label>}
    </div>}
    <button type="button" className="primary" disabled={busy || !preflight?.can_start || !allConfirmed}
      onClick={() => onStart(confirmations)}>开始测试</button>
  </section>;
}
