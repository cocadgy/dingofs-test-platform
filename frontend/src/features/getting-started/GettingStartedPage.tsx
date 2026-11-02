import { useState } from "react";
import { GuidedMachineForm } from "./GuidedMachineForm";
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

export function GettingStartedPage({ route, onNavigate, onDirty }: {
  route: "chooser" | "machine";
  onNavigate: (hash: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [action, setAction] = useState<string>("machine");
  const [comingSoon, setComingSoon] = useState(false);
  if (route === "machine") return <section className="getting-started"><p className="eyebrow">GETTING STARTED / MACHINE</p><h1>添加机器</h1><GuidedMachineForm onDirty={onDirty} onBack={() => onNavigate("#/start")} /></section>;
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
          <button className="primary" type="button" onClick={() => action === "machine" ? onNavigate("#/start/machine") : setComingSoon(true)}>下一步</button>
        </div>
      )}
    </section>
  );
}
