import { Spec, Tool } from "./types";
export type MatrixForm = Omit<
  Spec,
  | "layout"
  | "direct"
  | "rw"
  | "concurrency"
  | "file_count"
  | "rounds"
  | "iodepth"
  | "read_percent"
> & {
  mdtest_options_json?:string;
  layout: string[];
  direct: boolean[];
  rw: string[];
  concurrency: string;
  file_count: string;
  rounds: string;
  iodepth: string;
  read_percent: string;
};
export const candidates = (text: string) =>
  Array.from(new Set(text.split(/[,，\s]+/).filter(Boolean)));
export function matrixParameters(s: MatrixForm, mode: string) {
  const numbers = (
    key: "concurrency" | "file_count" | "rounds" | "iodepth" | "read_percent",
  ) => {
    const values = candidates(s[key]);
    if (!values.length || values.some((v) => !/^\d+$/.test(v)))
      throw new Error(`${s.tool} 的数值参数请选择整数`);
    return values.map(Number);
  };
  if (s.tool === "mdtest") return {
    tool:s.tool, concurrency:numbers("concurrency"), file_count:numbers("file_count"),
    rounds:numbers("rounds"), layout:s.layout, read_percent:undefined, mdtest_options:JSON.parse(s.mdtest_options_json || "{}"),
  };
  return {
    ...s,
    mdtest_options_json:undefined,
    mdtest_options:undefined,
    layout:undefined,
    concurrency: numbers("concurrency"),
    file_count: numbers("file_count"),
    rounds: numbers("rounds"),
    iodepth: numbers("iodepth"),
    read_percent: s.rw.some((r) => ["rw", "randrw"].includes(r))
      ? numbers("read_percent")
      : undefined,
    file_size: mode === "files" ? candidates(s.file_size) : undefined,
    total_size: mode === "total" ? candidates(s.total_size) : undefined,
    block_size: candidates(s.block_size),
  };
}
export const defaults = (tool: Tool): MatrixForm => ({
  tool,
  mdtest_options_json:"{}",
  layout:["unique"],
  direct: [true],
  concurrency: tool === "mdtest" ? "1" : "4",
  file_size: "256MiB",
  file_count: tool === "mdtest" ? "10000" : "4",
  total_size: "1GiB",
  block_size: "1MiB",
  rw: ["write"],
  rounds: "1",
  iodepth: "1",
  read_percent: "50",
});
export function estimatedCount(s: MatrixForm, mode: string) {
  if(s.tool==="mdtest") return candidates(s.concurrency).length*candidates(s.file_count).length*candidates(s.rounds).length*s.layout.length*Object.values(JSON.parse(s.mdtest_options_json || "{}") as Record<string,unknown>).reduce<number>((n,v)=>n*(Array.isArray(v)?v.length:1),1);
  return (
    s.direct.length *
    candidates(s.concurrency).length *
    candidates(s.file_count).length *
    candidates(mode === "files" ? s.file_size : s.total_size).length *
    candidates(s.block_size).length *
    candidates(s.rounds).length *
    candidates(s.iodepth).length *
    s.rw.reduce(
      (n, r) =>
        n +
        (["rw", "randrw"].includes(r) ? candidates(s.read_percent).length : 1),
      0,
    )
  );
}
export const modeLabels: Record<string, string> = {
  write: "顺序写",
  read: "顺序读",
  randwrite: "随机写",
  randread: "随机读",
  rw: "顺序混合读写",
  randrw: "随机混合读写",
};
