import type { GuidedConfiguration } from "./types";

export function RunOptionsStep({value,onChange}:{
  value:GuidedConfiguration;onChange:(patch:Partial<GuidedConfiguration>)=>void;
}) {
  return <section className="functional-card">
    <h1>运行设置</h1>
    <p>模块按框架顺序依次运行。最长运行时间从每个模块实际启动时计时。</p>
    <div className="functional-form"><label>任务名称
      <input value={value.name} maxLength={120} onChange={event => onChange({name:event.target.value})} />
    </label></div>
    <details><summary>高级选项</summary><div className="functional-form">
      <label>每个模块最长运行时间（分钟）
        <input type="number" min={1} max={1440} value={value.timeout_minutes}
          onChange={event => onChange({timeout_minutes:Number(event.target.value)})} />
      </label>
      <label>失败重试次数
        <input type="number" min={0} max={5} value={value.retries}
          onChange={event => onChange({retries:Number(event.target.value)})} />
      </label>
    </div></details>
    <p>环境收尾：普通套件成功后清理，失败默认保留现场；专用模块按其恢复和收尾规则执行。存在待处理现场时，后续模块不会启动。</p>
  </section>;
}
