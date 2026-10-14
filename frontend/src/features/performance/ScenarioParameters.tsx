import { Spec } from "./types";
import { modeLabels } from "./matrix";
export const formatBytes = (value: string | number) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let v = n,
    i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${Number(v.toFixed(2))} ${units[i]}`;
};
export function ScenarioParameters({ spec }: { spec: Spec }) {
  if(spec.tool==="mdtest")return <span className="performance-parameters">自定义 mdtest · MPI {spec.concurrency} 进程<br/>{spec.file_count} 个条目（显式 -n / -I 优先） · {spec.layout==="shared"?"共享目录":"各进程独立目录"} · {spec.rounds} 轮{spec.mdtest_options && Object.keys(spec.mdtest_options).length>0 && <><br/>{Object.entries(spec.mdtest_options).map(([k,v])=>`${k}=${v}`).join(" · ")}</>}</span>;
  return (
    <span className="performance-parameters">
      {modeLabels[spec.rw] || spec.rw} · {spec.direct ? "Direct" : "Buffered"} ·
      并发 {spec.concurrency}
      <br />
      {formatBytes(spec.file_size)} × {spec.file_count} 文件 · Block{" "}
      {formatBytes(spec.block_size)}
      <br />
      深度 {spec.iodepth} · {spec.rounds} 轮
      {spec.read_percent != null ? ` · 读 ${spec.read_percent}%` : ""}
    </span>
  );
}
