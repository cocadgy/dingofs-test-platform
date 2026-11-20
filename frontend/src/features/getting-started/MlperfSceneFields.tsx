import type { GuidedPerformanceForm } from './guidedPerformanceModel';

export function MlperfSceneFields({form, change}: {form:GuidedPerformanceForm; change:(value:Partial<GuidedPerformanceForm>)=>void}) {
  return <>
    <label>MLPerf 场景<select value={form.mlperfScenario} onChange={e => change({mlperfScenario:e.target.value as GuidedPerformanceForm['mlperfScenario']})}><option value="training">训练 I/O</option><option value="checkpointing">Checkpoint 检查点</option><option value="kvcache">KV Cache 缓存</option></select></label>
    {form.mlperfScenario === 'checkpointing' && <>
      <label>检查点模型<select value={form.checkpointModel} onChange={e => change({checkpointModel:e.target.value as GuidedPerformanceForm['checkpointModel']})}><option value="custom">自定义大小（适合小规模测试）</option><option value="llama3-8b">Llama3 8B（完整模型，8 个进程）</option></select></label>
      <label>检查点模式<select value={form.checkpointMode} onChange={e => change({checkpointMode:e.target.value as GuidedPerformanceForm['checkpointMode']})}><option value="write-read">写入后读取</option><option value="write">仅写入</option><option value="read">仅测读取（先准备数据）</option></select></label>
      <label>每轮检查点次数<input type="number" min="1" max="1000" value={form.checkpointCount} onChange={e => change({checkpointCount:Number(e.target.value)})} /></label>
      <p className="guided-performance-note">自定义模型使用上方数据量作为单个检查点总大小，按进程分配；Llama3 8B 使用原始模型规模，单次约 105 GiB，不采用自定义大小。只读模式先准备数据，准备耗时不计入读取指标。均为内部对比测试。</p>
    </>}
    {form.mlperfScenario === 'kvcache' && <>
      <label>KV Cache 模型<select value={form.kvModel} onChange={e => change({kvModel:e.target.value})}>{['tiny-1b','mistral-7b','llama2-7b','llama3.1-8b','llama3.1-70b-instruct'].map(model => <option key={model}>{model}</option>)}</select></label>
      <label>KV Cache 每轮时长（秒）<input type="number" min="1" max="86400" value={form.duration * ({seconds:1,minutes:60,hours:3600}[form.durationUnit])} onChange={e => change({duration:Number(e.target.value),durationUnit:'seconds'})} /></label>
      <p className="guided-performance-note">上方数据量是存储缓存层容量上限，不是实际写入量。并发数表示模拟用户数；默认 GPU/CPU 缓存层均为 0，使请求使用存储层。无需下载模型权重。</p>
      <details><summary>缓存层高级选项</summary><div className="guided-performance-fields">
        <label>GPU 缓存层（GiB）<input type="number" min="0" value={form.gpuMemoryGiB} onChange={e => change({gpuMemoryGiB:Number(e.target.value)})} /></label>
        <label>CPU 缓存层（GiB）<input type="number" min="0" value={form.cpuMemoryGiB} onChange={e => change({cpuMemoryGiB:Number(e.target.value)})} /></label>
      </div></details>
    </>}
  </>;
}
