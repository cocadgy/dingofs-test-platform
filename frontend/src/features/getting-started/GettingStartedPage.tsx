import { useState } from "react";
import { GuidedMachineForm } from "./GuidedMachineForm";
import { DiscoverClusters } from "../clusters/DiscoverClusters";
import "./getting-started.css";

const actions = [
  ["machine", "添加机器"],
  ["cluster", "添加集群"],
  ["filesystem", "创建文件系统"],
  ["cache", "创建缓存组"],
  ["mount", "挂载文件系统"],
  ["functional", "功能测试"],
  ["performance", "性能测试"],
] as const;

export function GettingStartedPage({ route, onNavigate, onDirty, admin = false, userId }: {
  route: "chooser" | "machine" | "cluster" | "cluster-machine";
  onNavigate: (hash: string) => void;
  onDirty: (dirty: boolean) => void;
  admin?: boolean;
  userId?: string;
}) {
  const [action, setAction] = useState<string>("machine");
  const [comingSoon, setComingSoon] = useState(false);
  const [newMachineId, setNewMachineId] = useState<string>();
  const [importedIds, setImportedIds] = useState<string[]>([]);
  if (route === "machine") return <section className="getting-started"><p className="eyebrow">GETTING STARTED / MACHINE</p><h1>添加机器</h1><GuidedMachineForm onDirty={onDirty} onBack={() => onNavigate("#/start")} /></section>;
  if (route === "cluster-machine") return <section className="getting-started"><p className="eyebrow">GETTING STARTED / CLUSTER / MACHINE</p><h1>先添加执行机器</h1><GuidedMachineForm onDirty={onDirty} onBack={() => onNavigate("#/start/cluster")} onCreated={(id) => { setNewMachineId(id); onNavigate("#/start/cluster"); }} /></section>;
  if (route === "cluster") return <section className="getting-started"><p className="eyebrow">GETTING STARTED / CLUSTER</p><h1>添加集群</h1>{importedIds.length ? <div className="getting-started-card"><h2>集群添加成功</h2>{importedIds.map((id) => <button className="primary" type="button" key={id} onClick={() => onNavigate(`#/clusters/${encodeURIComponent(id)}`)}>查看集群</button>)}<button type="button" onClick={() => onNavigate("#/start")}>返回开始页</button></div> : <DiscoverClusters guided admin={admin} userId={userId} initialMachineId={newMachineId} onAddMachine={() => onNavigate("#/start/cluster/machine")} onClose={() => onNavigate("#/start")} onImported={setImportedIds} />}</section>;
  return (
    <section className="getting-started">
      <p className="eyebrow">GETTING STARTED</p>
      <h1>开始</h1>
      <p className="muted">选择接下来想完成的任务，我们会一步步引导你。</p>
      {comingSoon ? (
        <div className="getting-started-card">
          <h2>即将支持</h2>
          <p>这项引导正在建设中。</p>
          <button type="button" onClick={() => setComingSoon(false)}>返回开始页</button>
        </div>
      ) : (
        <div className="getting-started-card">
          <label htmlFor="start-action">想做什么</label>
          <select id="start-action" value={action} onChange={(event) => setAction(event.target.value)}>
            {actions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button className="primary" type="button" onClick={() => action === "machine" ? onNavigate("#/start/machine") : action === "cluster" ? onNavigate("#/start/cluster") : setComingSoon(true)}>下一步</button>
        </div>
      )}
    </section>
  );
}
