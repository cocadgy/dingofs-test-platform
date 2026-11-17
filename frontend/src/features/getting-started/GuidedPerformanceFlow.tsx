import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Options, Preview, Run } from "../performance/types";
import { buildGuidedPerformancePayload, defaultGuidedPerformanceForm, guidedPerformanceTotals, validateGuidedPerformance, type GuidedPerformanceForm } from "./guidedPerformanceModel";
import "./guided-performance.css";

const steps = ["测试位置", "选择工具", "设置参数", "确认启动"];
const sizeUnits = ["MiB", "GiB", "TiB"] as const;
const blockUnits = ["KiB", ...sizeUnits] as const;
const modes = [["write", "顺序写"], ["read", "顺序读"], ["randwrite", "随机写"], ["randread", "随机读"], ["rw", "混合顺序读写"], ["randrw", "混合随机读写"]];
const formatBytes = (value: number) => value >= 1024 ** 4 ? `${value / 1024 ** 4} TiB` : value >= 1024 ** 3 ? `${value / 1024 ** 3} GiB` : `${value / 1024 ** 2} MiB`;
const formatDuration = (value: number) => value >= 3600 ? `${(value / 3600).toFixed(1)} 小时` : value >= 60 ? `${(value / 60).toFixed(1)} 分钟` : `${value} 秒`;

export function GuidedPerformanceFlow({ onNavigate, onDirty }: { onNavigate: (hash: string, confirmed?: boolean) => void; onDirty: (dirty: boolean) => void }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(defaultGuidedPerformanceForm);
  const [options, setOptions] = useState<Options>({ machines: [], mounts: [] });
  const [optionsBusy, setOptionsBusy] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview>();
  const [previewKey, setPreviewKey] = useState("");
  const revision = useRef(0);
  const loadingId = useRef(0);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const payload = buildGuidedPerformancePayload(form);
  const key = JSON.stringify(payload);
  const totals = guidedPerformanceTotals(form);
  const machine = options.machines.find(item => item.id === form.machineId);
  const mounts = options.mounts.filter(item => item.machine_id === form.machineId && item.path && item.state === "mounted");

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; onDirty(false); }; }, [onDirty]);
  async function loadOptions() {
    const id = ++loadingId.current;
    setOptionsBusy(true); setError("");
    try {
      const result = await api<Options>("/performance/options");
      if (mounted.current && id === loadingId.current) {
        setOptions(result);
        setForm(previous => {
          const validMachine = result.machines.some(item => item.id === previous.machineId && !item.maintenance);
          const validMount = result.mounts.some(item => item.machine_id === previous.machineId && item.path === previous.targetPath && item.state === "mounted");
          return validMachine ? previous.targetKind === "mount" && !validMount ? { ...previous, targetPath: "" } : previous : { ...previous, machineId: "", targetPath: "" };
        });
      }
    } catch (cause) { if (mounted.current && id === loadingId.current) setError((cause as Error).message); }
    finally { if (mounted.current && id === loadingId.current) setOptionsBusy(false); }
  }
  useEffect(() => { void loadOptions(); return () => { loadingId.current++; }; }, []);
  function change(patch: Partial<GuidedPerformanceForm>) {
    revision.current++;
    setForm(previous => ({ ...previous, ...patch }));
    setPreview(undefined); setPreviewKey(""); setError(""); onDirty(true);
  }
  function next() {
    if (step === 0) {
      if (!machine || machine.maintenance) { setError("请选择可用的目标机器"); return; }
      if (!form.targetPath.startsWith("/") || form.targetPath === "/" || form.targetPath.includes("..")) { setError("请填写有效的绝对目标目录"); return; }
      if (form.targetKind === "mount" && !mounts.some(item => item.path === form.targetPath)) { setError("请选择该机器上可用的挂载目录"); return; }
    } else if (step === 1 && !form.tools.length) { setError("请选择至少一种测试工具"); return; }
    else if (step === 2) { const problem = validateGuidedPerformance(form); if (problem) { setError(problem); return; } }
    setError(""); setStep(value => value + 1);
  }
  async function prepare() {
    const problem = validateGuidedPerformance(form);
    if (problem) { setError(problem); return; }
    if (busy) return;
    const currentRevision = revision.current;
    setBusy(true); setError(""); setPreview(undefined); setPreviewKey("");
    try {
      const result = await api<Preview>("/performance/preview", "POST", payload);
      if (mounted.current && revision.current === currentRevision) { setPreview(result); setPreviewKey(key); }
    } catch (cause) { if (mounted.current && revision.current === currentRevision) setError((cause as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function start() {
    if (submitting.current || busy || !preview || previewKey !== key) return;
    submitting.current = true; setBusy(true); setError("");
    try {
      const result = await api<Run>("/performance/runs", "POST", payload);
      if (!result?.id) throw new Error("服务器未确认任务编号，请在任务列表中核实后再操作");
      if (mounted.current) { onDirty(false); onNavigate("#/performance/" + encodeURIComponent(result.id), true); }
    } catch (cause) { if (mounted.current) setError((cause as Error).message + "。提交状态可能未知，请先检查任务列表，避免重复启动。"); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  return <section className="getting-started guided-performance-flow">
    <p className="eyebrow">GETTING STARTED / PERFORMANCE</p><h1>性能测试引导</h1>
    <p className="muted">在选定机器上运行 fio 和 elbencho。每种工具会保留自己的测试数据，结果在现有任务详情中查看。</p>
    <nav className="guided-performance-steps" aria-label="引导步骤">{steps.map((label, index) => <span key={label} aria-current={index === step ? "step" : undefined}>{index + 1}. {label}</span>)}</nav>
    <div className="getting-started-card">
      <h2>{steps[step]}</h2>
      {error && <p role="alert" className="error">{error}</p>}
      {step === 0 && <div className="guided-performance-fields">
        {optionsBusy && <p role="status">正在加载机器和挂载目录…</p>}
        {!optionsBusy && !options.machines.some(item => !item.maintenance) && <p>暂无可用机器。请先添加机器或等待维护结束。</p>}
        <label>目标机器<select value={form.machineId} onChange={event => change({ machineId: event.target.value, targetPath: "" })} disabled={optionsBusy}>
          <option value="">请选择机器</option>{options.machines.map(item => <option key={item.id} value={item.id} disabled={item.maintenance}>{item.name} · {item.address} · SSH {item.ssh_user}{item.maintenance ? "（维护中）" : ""}</option>)}
        </select></label>
        {machine && <p className="guided-performance-note">{machine.name} · {machine.address} · SSH 用户 {machine.ssh_user}</p>}
        <label>测试位置<select value={form.targetKind} onChange={event => change({ targetKind: event.target.value as GuidedPerformanceForm["targetKind"], targetPath: "" })}><option value="directory">指定目录</option><option value="mount">已保存的挂载文件系统</option></select></label>
        {form.targetKind === "mount" ? <label>挂载目录<select aria-label="挂载目录" value={form.targetPath} onChange={event => change({ targetPath: event.target.value })}><option value="">请选择挂载目录</option>{mounts.map(item => <option key={item.id} value={item.path}>{item.name} · {item.path}</option>)}</select>{form.machineId && !mounts.length && <small>这台机器暂无可用的已挂载文件系统。</small>}</label>
          : <label>目标目录<input aria-label="目标目录" value={form.targetPath} placeholder="例如 /mnt/disk1/benchmark" onChange={event => change({ targetPath: event.target.value })} /><small>填写绝对目录；任务只在其下创建专用子目录。</small></label>}
        <button type="button" onClick={() => void loadOptions()} disabled={optionsBusy}>重新加载选项</button>
      </div>}
      {step === 1 && <div className="guided-performance-tools">
        <label><input aria-label="fio" type="checkbox" checked={form.tools.includes("fio")} onChange={event => change({ tools: event.target.checked ? [...form.tools, "fio"] : form.tools.filter(tool => tool !== "fio") })} /><span><strong>fio</strong><small>常用块 I/O 测试，查看吞吐、IOPS 和延迟。</small></span></label>
        <label><input aria-label="elbencho" type="checkbox" checked={form.tools.includes("elbencho")} onChange={event => change({ tools: event.target.checked ? [...form.tools, "elbencho"] : form.tools.filter(tool => tool !== "elbencho") })} /><span><strong>elbencho</strong><small>面向文件系统的并发吞吐测试。</small></span></label>
        <p className="muted">需要 mdtest 或参数矩阵？<button type="button" onClick={() => onNavigate("#/performance")}>打开高级性能测试</button></p>
      </div>}
      {step === 2 && <div className="guided-performance-fields">
        <label>任务名称<input value={form.name} maxLength={120} onChange={event => change({ name: event.target.value })} /></label>
        <div className="guided-performance-pair"><label>测量时长<input type="number" min="1" value={form.duration} onChange={event => change({ duration: Number(event.target.value) })} /></label><label>时长单位<select aria-label="时长单位" value={form.durationUnit} onChange={event => change({ durationUnit: event.target.value as GuidedPerformanceForm["durationUnit"] })}><option value="seconds">秒</option><option value="minutes">分钟</option><option value="hours">小时</option></select></label></div>
        <small>每种工具每轮各测量一次。准备数据与同步时间不计入测量时长。</small>
        <div className="guided-performance-pair"><label>每种工具数据量<input type="number" min="1" value={form.dataset} onChange={event => change({ dataset: Number(event.target.value) })} /></label><label>数据量单位<select value={form.datasetUnit} onChange={event => change({ datasetUnit: event.target.value as GuidedPerformanceForm["datasetUnit"] })}>{sizeUnits.map(unit => <option key={unit}>{unit}</option>)}</select></label></div>
        <label>读写模式<select value={form.rw} onChange={event => change({ rw: event.target.value })}>{modes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <p className="guided-performance-estimate">预计测量时间：{formatDuration(totals.measuredSeconds)} · 合计保留数据：{formatBytes(totals.combinedBytes)}</p>
        <details><summary>高级选项</summary><div className="guided-performance-fields">
          <label>并发数<input type="number" min="1" max="1024" value={form.concurrency} onChange={event => change({ concurrency: Number(event.target.value) })} /></label>
          <div className="guided-performance-pair"><label>块大小<input type="number" min="1" value={form.blockSize} onChange={event => change({ blockSize: Number(event.target.value) })} /></label><label>块大小单位<select value={form.blockUnit} onChange={event => change({ blockUnit: event.target.value as GuidedPerformanceForm["blockUnit"] })}>{blockUnits.map(unit => <option key={unit}>{unit}</option>)}</select></label></div>
          <label>轮数<input type="number" min="1" max="100" value={form.rounds} onChange={event => change({ rounds: Number(event.target.value) })} /></label>
          <label>I/O 深度<input type="number" min="1" max="1024" value={form.iodepth} onChange={event => change({ iodepth: Number(event.target.value) })} /></label>
          {["rw", "randrw"].includes(form.rw) && <label>混合读比例（%）<input type="number" min="0" max="100" value={form.readPercent} onChange={event => change({ readPercent: Number(event.target.value) })} /></label>}
          <label className="guided-performance-check"><input type="checkbox" checked={form.direct} onChange={event => change({ direct: event.target.checked })} />Direct I/O</label>
          <label className="guided-performance-check"><input type="checkbox" checked={form.cleanupData} onChange={event => change({ cleanupData: event.target.checked })} />全部成功后清理任务数据</label>
          <label>任务总超时（分钟）<input type="number" min="1" placeholder={`默认 ${totals.defaultTimeoutMinutes} 分钟`} value={form.timeoutMinutes || ""} onChange={event => change({ timeoutMinutes: event.target.value ? Number(event.target.value) : 0 })} /><small>留空采用 {totals.defaultTimeoutMinutes} 分钟；准备数据耗时会随环境变化。</small></label>
        </div></details>
      </div>}
      {step === 3 && <div className="guided-performance-confirm">
        <dl><div><dt>机器</dt><dd>{machine?.name} · {machine?.address} · SSH {machine?.ssh_user}</dd></div><div><dt>目标</dt><dd>{form.targetKind === "mount" ? "挂载文件系统" : "指定目录"} · {form.targetPath}</dd></div><div><dt>工具</dt><dd>{form.tools.join("、")}</dd></div><div><dt>每工具每轮测量</dt><dd>{formatDuration(totals.runtimeSeconds)}</dd></div><div><dt>每工具数据量</dt><dd>{formatBytes(totals.datasetBytes)}</dd></div><div><dt>预计总测量</dt><dd>{formatDuration(totals.measuredSeconds)}</dd></div><div><dt>合计保留数据</dt><dd>{formatBytes(totals.combinedBytes)}</dd></div><div><dt>总超时</dt><dd>{payload.timeout_minutes} 分钟</dd></div></dl>
        <p className="muted">预览会验证配置并显示生成的 DTT 命令；它不检查远程工具是否可用。</p>
        <button type="button" onClick={() => void prepare()} disabled={busy}>生成预览</button>
        {preview && previewKey === key && <div className="guided-performance-preview"><h3>配置预览</h3>{preview.tests.map((test, index) => <div key={`${test.tool}-${index}`}><strong>{test.tool}</strong><pre>{test.command}</pre><details><summary>规范化参数</summary><pre>{JSON.stringify(test.parameters, null, 2)}</pre></details></div>)}</div>}
        <button className="primary" type="button" onClick={() => void start()} disabled={busy || !preview || previewKey !== key}>开始测试</button>
      </div>}
      <div className="getting-started-actions">{step > 0 && <button type="button" disabled={busy} onClick={() => { setError(""); setStep(value => value - 1); }}>上一步</button>}{step < 3 && <button className="primary" type="button" disabled={optionsBusy || busy} onClick={next}>下一步</button>}{step === 0 && <button type="button" onClick={() => onNavigate("#/start")}>返回开始页</button>}</div>
    </div>
  </section>;
}
