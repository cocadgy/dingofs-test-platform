import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { requestId } from "../resources/requestId";
import { CaseStep } from "../functional/CaseStep";
import { moduleLabels } from "../functional/types";
import { EnvironmentStep, environmentReason } from "../functional/EnvironmentStep";
import { PreflightStep } from "../functional/PreflightStep";
import { RunOptionsStep } from "../functional/RunOptionsStep";
import type { GuidedCompatibility, GuidedConfiguration, GuidedMetadata, GuidedModulePlan,
  GuidedPreflight, Options, Profile } from "../functional/types";
import { useFunctionalDraft } from "./useFunctionalDraft";
import "../functional/functional.css";

export type GuidedFunctionalProps = {
  userId:string;onNavigate:(hash:string)=>void;onDirty:(dirty:boolean)=>void;
};
const initial:GuidedConfiguration = {
  kind:"existing-environments",version:2,cluster_id:"",default_environment_id:"",
  module_plans:[],name:"",retries:0,timeout_minutes:1440,
};
const labels = ["选择测试环境","选择模块和用例","运行设置","检查并启动"];
const message = (reason:unknown) => reason instanceof Error ? reason.message : String(reason);
const selectedCases = (plans:GuidedModulePlan[]) =>
  Object.fromEntries(plans.map(plan => [plan.module,plan.cases]));
const requestedDraft = () => {
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  return params.get("draft") || "";
};

export function GuidedFunctionalFlow({userId,onNavigate,onDirty}:GuidedFunctionalProps) {
  const [options,setOptions] = useState<Options>();
  const [profiles,setProfiles] = useState<Profile[]>([]);
  const [metadata,setMetadata] = useState<GuidedMetadata>();
  const [configuration,setConfiguration] = useState<GuideConfig>(initial);
  const [step,setStep] = useState(1);
  const [compatibility,setCompatibility] = useState<GuidedCompatibility|null>(null);
  const [checking,setChecking] = useState(false);
  const [preflight,setPreflight] = useState<GuidedPreflight|null>(null);
  const [toolJob,setToolJob] = useState<{id:string;state:string;message?:string}>();
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [changed,setChanged] = useState(false);
  const [loading,setLoading] = useState(true);
  const [submittedRun,setSubmittedRun] = useState("");
  const lastSaved = useRef("");
  const submitKey = useRef("");
  const draft = useFunctionalDraft(userId,requestedDraft());

  // Navigate after clearing the parent's dirty state has committed. A timer
  // would keep the pre-submit callback and incorrectly ask to leave a draft.
  useEffect(() => {
    if (submittedRun) onNavigate(`#/functional/${encodeURIComponent(submittedRun)}`);
  },[submittedRun,onNavigate]);

  useEffect(() => {
    let live=true;
    Promise.all([api<Options>("/functional/options"),api<Profile[]>("/functional/environments"),
      api<GuidedMetadata>("/functional/guided/metadata")])
      .then(([catalog,environments,meta]) => {
        if (!live) return;
        setOptions(catalog);setProfiles(environments);setMetadata(meta);
        if (meta.clusters.length === 1) {
          setConfiguration(value => value.cluster_id ? value : {...value,cluster_id:meta.clusters[0].id,
            name:value.name || `功能测试 ${meta.clusters[0].name} ${new Date().toLocaleString()}`});
        }
      })
      .catch(reason => {if (live) setError(message(reason));})
      .finally(() => {if (live) setLoading(false);});
    return () => {live=false;};
  },[userId]);

  useEffect(() => {
    if (!draft.restored) return;
    setConfiguration(draft.restored.configuration);
    setStep(Math.min(4,Math.max(1,draft.restored.step)));
    setCompatibility(null);setPreflight(null);
    lastSaved.current=JSON.stringify([draft.restored.configuration,draft.restored.step]);
    onDirty(true);
  },[draft.restored,onDirty]);

  useEffect(() => {
    if (!changed) return;
    const key=JSON.stringify([configuration,step]);
    if (key === lastSaved.current) return;
    const timer=window.setTimeout(() => {
      void draft.save(configuration,step).then(() => {lastSaved.current=key;}).catch(() => {});
    },1000);
    return () => window.clearTimeout(timer);
  },[configuration,step,changed,draft.save]);

  useEffect(() => {
    if (!toolJob || !["pending","running"].includes(toolJob.state) || !metadata) return;
    const machine=metadata.clusters.find(item => item.id === configuration.cluster_id)?.management_machine;
    if (!machine) return;
    let live=true;
    const timer=window.setInterval(() => {
      void api<{id:string;state:string;message?:string}[]>(`/machines/${machine.id}/tool-jobs`)
        .then(rows => {
          const current=rows.find(item => item.id === toolJob.id);
          if (!live || !current) return;
          setToolJob(current);
          if (current.state === "success") {
            setPreflight(null);
            setError("DTT 安装完成。请重新检查环境。");
          } else if (current.state === "failed") setError(current.message || "DTT 安装失败");
        }).catch(reason => {if (live) setError(message(reason));});
    },2000);
    return () => {live=false;window.clearInterval(timer);};
  },[toolJob,metadata,configuration.cluster_id]);

  function update(patch:Partial<GuidedConfiguration>) {
    setConfiguration(value => ({...value,...patch}));
    setChanged(true);onDirty(true);
    setCompatibility(null);setPreflight(null);submitKey.current="";
    setError("");
  }
  function clusterChanged(id:string) {
    const cluster=metadata?.clusters.find(item => item.id === id);
    update({cluster_id:id,default_environment_id:"",
      module_plans:configuration.module_plans.map(plan => ({...plan,environment_profile_id:"",environment_profile_revision:0})),
      name:configuration.name || (cluster ? `功能测试 ${cluster.name} ${new Date().toLocaleString()}` : "")});
  }
  function environmentChanged(id:string) {
    const profile=profiles.find(item => item.id === id);
    update({default_environment_id:id,module_plans:configuration.module_plans.map(plan =>
      plan.environment_profile_id === configuration.default_environment_id || !plan.environment_profile_id
        ? {...plan,environment_profile_id:id,environment_profile_revision:profile?.revision || 0} : plan)});
  }
  function casesChanged(value:Record<string,string[]>) {
    update({module_plans:Object.entries(value).filter(([,cases]) => cases.length).map(([module,cases]) => {
      const old=configuration.module_plans.find(item => item.module === module);
      const id=old?.environment_profile_id || configuration.default_environment_id;
      return {module,cases,environment_profile_id:id,
        environment_profile_revision:profiles.find(item => item.id === id)?.revision || 0};
    })});
  }
  function choiceChanged(module:string,id:string) {
    update({module_plans:configuration.module_plans.map(plan => plan.module === module
      ? {...plan,environment_profile_id:id,environment_profile_revision:profiles.find(item => item.id === id)?.revision || 0}
      : plan)});
  }
  function applyChoice(module:string,id:string) {
    const revision=profiles.find(item => item.id === id)?.revision || 0;
    update({module_plans:configuration.module_plans.map(plan => plan.module === module
      ? plan : {...plan,environment_profile_id:id,environment_profile_revision:revision})});
  }
  function spec(value=configuration) {
    if (!options) throw new Error("用例目录尚未加载");
    return {name:value.name.trim() || "功能测试",cluster_id:value.cluster_id,
      module_plans:value.module_plans.filter(plan => plan.environment_profile_id && plan.environment_profile_revision),
      catalog_digest:options.digest,retries:value.retries,timeout_minutes:value.timeout_minutes};
  }
  async function inspectPlans(value=configuration) {
    if (!value.module_plans.length) throw new Error("请至少选择一个测试用例");
    if (value.module_plans.some(plan => !plan.environment_profile_id || !plan.environment_profile_revision))
      throw new Error("请为每个已选模块选择测试环境");
    const result=await api<GuidedCompatibility>("/functional/guided/compatibility","POST",spec(value));
    setCompatibility(result);
    const invalid=value.module_plans.find(plan => !result.modules[plan.module]?.compatible);
    if (invalid) throw new Error(`${moduleLabels[invalid.module] || invalid.module} 环境不兼容：${result.modules[invalid.module]?.reasons.join("；") || "请明确选择兼容环境"}`);
    return result;
  }
  useEffect(() => {
    if (step < 2 || !options || !configuration.module_plans.length || !metadata?.enabled) return;
    if (configuration.module_plans.some(plan => !plan.environment_profile_id || !plan.environment_profile_revision)) return;
    let live=true;
    setChecking(true);
    api<GuidedCompatibility>("/functional/guided/compatibility","POST",spec())
      .then(result => {if (live) setCompatibility(result);})
      .catch(reason => {if (live) setError(message(reason));})
      .finally(() => {if (live) setChecking(false);});
    return () => {live=false;};
  },[step,options,configuration,metadata?.enabled]);

  async function save(nextStep:number) {
    const key=JSON.stringify([configuration,nextStep]);
    if (key === lastSaved.current && draft.draft) return draft.draft;
    const row=await draft.save(configuration,nextStep);
    lastSaved.current=key;
    return row;
  }
  async function next() {
    setError("");
    try {
      if (step === 1) {
        if (!configuration.cluster_id) throw new Error("请选择目标集群");
        if (!configuration.default_environment_id) throw new Error("请选择测试环境");
        const profile=profiles.find(item => item.id === configuration.default_environment_id);
        if (!profile || !metadata || environmentReason(profile,configuration.cluster_id,metadata))
          throw new Error("所选环境不可用");
        await api(`/functional/environments/${profile.id}/validate?cluster_id=${encodeURIComponent(configuration.cluster_id)}`);
      }
      if (step === 2) await inspectPlans();
      if (step === 3 && (!configuration.name.trim() || !Number.isInteger(configuration.retries)
        || configuration.retries < 0 || configuration.retries > 5
        || !Number.isInteger(configuration.timeout_minutes) || configuration.timeout_minutes < 1
        || configuration.timeout_minutes > 1440)) throw new Error("任务名称、重试次数或运行时间无效");
      await save(Math.min(4,step+1));
      setStep(value => Math.min(4,value+1));
    } catch (reason) {setError(message(reason));}
  }
  async function check() {
    setBusy(true);setError("");setPreflight(null);
    try {
      await inspectPlans();
      const result=await api<GuidedPreflight>("/functional/preflight","POST",spec());
      setPreflight(result);
    } catch (reason) {setError(message(reason));}
    finally {setBusy(false);}
  }
  async function install() {
    const machine=metadata?.clusters.find(item => item.id === configuration.cluster_id)?.management_machine;
    if (!machine) return;
    if (!window.confirm(`将在 ${machine.name}（${machine.address}）以 ${machine.ssh_user} 安装或更新平台配置的 DTT 启动文件与镜像；确认提交工具包任务？`)) return;
    setBusy(true);setError("");
    try {
      const result=await api<{id:string;state:string;message?:string}>(`/machines/${machine.id}/tool-jobs`,
        "POST",{action:"auto_install",tool:"dtt"});
      setToolJob(result);setPreflight(null);
      setError(result.state === "success" ? "DTT 安装完成。请重新检查环境。" : "DTT 安装任务已提交，完成后请重新检查环境。");
    } catch (reason) {setError(message(reason));}
    finally {setBusy(false);}
  }
  async function start(confirmed:string[]) {
    if (!preflight?.can_start || !preflight.token) return;
    setBusy(true);setError("");
    try {
      const row=await save(4);
      if (!submitKey.current) submitKey.current=requestId();
      const result=await api<{id:string}>("/functional/runs","POST",{
        ...spec(),version:2,idempotency_key:submitKey.current,preflight_token:preflight.token,
        confirmed_impacts:confirmed,draft_id:row.id,draft_revision:row.revision,
      });
      onDirty(false);
      setSubmittedRun(result.id);
    } catch (reason) {setError(message(reason));}
    finally {setBusy(false);}
  }
  function leave() {
    if (!window.confirm(changed ? "有未保存修改，确定离开引导流程？" : "确定离开当前引导流程？")) return;
    onDirty(false);onNavigate("#/start");
  }

  if (loading || draft.loading || !metadata || !options) return <section className="functional-page"><p>正在载入功能测试引导…</p>{error && <p role="alert">{error}</p>}</section>;
  if (!metadata.enabled) return <section className="functional-page"><h1>功能测试引导尚未启用</h1><p>管理员启用并验证运行时后才能使用。</p><button onClick={leave}>返回开始页</button></section>;
  return <section className="functional-page guided-functional">
    <header><div><p className="eyebrow">GETTING STARTED / FUNCTIONAL TEST</p>
      <p>基于已有环境的功能测试 · 第 {step} / 4 步</p></div>
      <button type="button" onClick={leave}>返回开始页</button></header>
    <ol className="guided-functional-steps">{labels.map((label,index) =>
      <li key={label} aria-current={step === index+1 ? "step" : undefined}>{index+1}. {label}</li>)}</ol>
    {draft.suggested.length > 0 && <div className="functional-card">
      <h2>恢复未提交草稿？</h2>
      {draft.suggested.map(row => <p key={row.id}>{row.name} · 第 {row.step} 步
        <button type="button" onClick={() => onNavigate(`#/start/functional?draft=${encodeURIComponent(row.id)}`)}>恢复此草稿</button></p>)}
      <button type="button" onClick={draft.dismissSuggestions}>新建配置</button>
    </div>}
    {(error || draft.error) && <p role="alert" className="error">{error || draft.error}</p>}
    {step === 1 && <EnvironmentStep metadata={metadata} profiles={profiles}
      clusterId={configuration.cluster_id} environmentId={configuration.default_environment_id}
      onCluster={clusterChanged} onEnvironment={environmentChanged}
      onRefresh={() => {void api<Profile[]>("/functional/environments").then(setProfiles).catch(reason => setError(message(reason)));}} />}
    {step === 2 && <CaseStep options={options} metadata={metadata} profiles={profiles}
      clusterId={configuration.cluster_id} defaultEnvironmentId={configuration.default_environment_id}
      selected={selectedCases(configuration.module_plans)} onSelected={casesChanged}
      choices={Object.fromEntries(configuration.module_plans.filter(plan =>
        plan.environment_profile_id !== configuration.default_environment_id).map(plan => [plan.module,plan.environment_profile_id]))}
      onChoice={choiceChanged} onApply={applyChoice} compatibility={compatibility} checking={checking} />}
    {step === 3 && <RunOptionsStep value={configuration} onChange={update} />}
    {step === 4 && <PreflightStep configuration={configuration} profiles={profiles} metadata={metadata}
      compatibility={compatibility} preflight={preflight} busy={busy}
      onCheck={() => {void check();}} onInstall={() => {void install();}}
      onStart={confirmed => {void start(confirmed);}} />}
    <div className="functional-actions">
      {step > 1 && <button type="button" onClick={() => {setPreflight(null);setStep(value => value-1);}}>上一步</button>}
      {step < 4 && <button type="button" className="primary" disabled={busy} onClick={() => {void next();}}>下一步</button>}
      {draft.draft && <span>草稿已保存 · 修订 {draft.draft.revision}</span>}
    </div>
  </section>;
}

type GuideConfig = GuidedConfiguration;
