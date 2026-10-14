import { MdtestOptions } from "./MdtestOptions";
import { MdtestOption } from "./types";
import { CandidateInput } from "./CandidateInput";
import { Tool } from "./types";
import { MatrixForm, candidates, estimatedCount, modeLabels } from "./matrix";

export function ToolParameters({
  catalog,
  tool,
  s,
  sizeMode,
  change,
  onSizeMode,
  onRemove,
}: {
  catalog?:MdtestOption[];
  tool: Tool;
  s: MatrixForm;
  sizeMode: string;
  change: (
    tool: Tool,
    key: keyof MatrixForm,
    value: string | boolean[] | string[],
  ) => void;
  onSizeMode: (value: string) => void;
  onRemove?: () => void;
}) {
  const input = (key: keyof MatrixForm, label: string, choices: string[]) => (
    <CandidateInput
      key={key}
      label={label}
      value={s[key] as string}
      choices={choices}
      defaultUnit={
        key === "block_size"
          ? "KiB"
          : ["file_size", "total_size"].includes(key)
            ? "MiB"
            : undefined
      }
      onChange={(value) => change(tool, key, value)}
    />
  );
  if(tool === "mdtest") return <section className="performance-tool-form">
    <div className="performance-tool-header"><h3>mdtest</h3><strong className="performance-combination-count">预计 {estimatedCount(s,sizeMode)} 个组合</strong>
      {onRemove && <button type="button" aria-label="删除 mdtest" onClick={onRemove}>删除工具</button>}</div>
    <p className="muted">使用 dtt -t mdtest -s custom 执行生成的脚本。默认测试空文件的创建、stat、读取与删除；可选择阶段和其他原生参数。常用参数支持多选，自动组合。</p>
    <div className="performance-config-section"><h4>并发与规模</h4><div className="form-grid">
      {input("concurrency","MPI 进程数",["1","2","4","8","16","32","64"])}
      {input("file_count","文件总数量",["100","1000","10000","100000","1000000"])}
      {input("rounds","测量轮次",["1","3","5"])}</div></div>
    <div className="performance-config-section"><h4>目录布局</h4><fieldset className="performance-enum"><legend>目录布局（多选）</legend>
      {[["unique","各进程独立目录"],["shared","共享目录"]].map(([value,label])=><label key={value}>
        <input type="checkbox" aria-label={"mdtest "+label} checked={s.layout.includes(value)}
          onChange={e=>change(tool,"layout",e.target.checked?[...s.layout,value]:s.layout.filter(v=>v!==value))}/>{label}</label>)}
    </fieldset></div>
    <MdtestOptions catalog={catalog || []} value={s.mdtest_options_json || "{}"} onChange={value=>change(tool,"mdtest_options_json",value)}/>
    <p className="muted">-i 由测量轮次设置，-u 由目录布局设置。-d 限定在本场景独立目录内。未指定阶段时执行全部阶段（包含删除）；取消清理不会禁用 mdtest 的删除阶段。仅 stat / 读取 / 删除不会自动准备数据。使用任务数扫描时，原生报告分别展示各任务数的结果。</p>
  </section>;
  return (
    <section className="performance-tool-form">
      <div className="performance-tool-header">
        <h3>{tool}</h3>
        <strong className="performance-combination-count">
          预计 {estimatedCount(s, sizeMode)} 个组合
        </strong>
        {onRemove && (
          <button type="button" aria-label={"删除 " + tool} onClick={onRemove}>
            删除工具
          </button>
        )}
      </div>
      <p className="muted">
        点击下方参数添加标签，标签内可删除；按数值或实际容量升序排列。自定义值每次添加一个。各参数自动交叉组合，预览时统一校验并去重。
      </p>
      <div className="performance-config-section">
        <h4>读写方式</h4>
        <fieldset className="performance-enum">
          <legend>读写模式（多选）</legend>
          {Object.entries(modeLabels).map(([value, label]) => (
            <label key={value}>
              <input
                type="checkbox"
                aria-label={tool + " " + label}
                checked={s.rw.includes(value)}
                onChange={(e) =>
                  change(
                    tool,
                    "rw",
                    e.target.checked
                      ? [...s.rw, value]
                      : s.rw.filter((x) => x !== value),
                  )
                }
              />
              {label}
            </label>
          ))}
        </fieldset>
        {s.rw.some((r) => ["rw", "randrw"].includes(r)) && (
          <section className="performance-mix-ratio">
            <h4>混合读写比例</h4>
            <p className="muted">
              默认读写各占 50%。选择或自定义读比例，写比例自动补足至
              100%；多选会生成独立场景。
            </p>
            {input("read_percent", "读比例（%）", ["30", "50", "70"])}
            <div
              className="performance-ratio-summary"
              aria-label="当前读写比例"
            >
              {candidates(s.read_percent)
                .map((v) => Number(v))
                .filter((v) => Number.isInteger(v) && v >= 0 && v <= 100)
                .sort((a, b) => a - b)
                .map((v) => (
                  <span key={v}>
                    读 {v}% / 写 {100 - v}%
                  </span>
                ))}
            </div>
          </section>
        )}
      </div>
      <div className="performance-config-section">
        <h4>并发与 I/O</h4>
        <fieldset className="performance-enum">
          <legend>Direct I/O（多选）</legend>
          {[true, false].map((value) => (
            <label key={String(value)}>
              <input
                type="checkbox"
                aria-label={tool + " Direct I/O " + (value ? "开启" : "关闭")}
                checked={s.direct.includes(value)}
                onChange={(e) =>
                  change(
                    tool,
                    "direct",
                    e.target.checked
                      ? [...s.direct, value]
                      : s.direct.filter((x) => x !== value),
                  )
                }
              />
              {value ? "开启" : "关闭（buffered）"}
            </label>
          ))}
        </fieldset>
        <div className="form-grid">
          {input("concurrency", tool === "fio" ? "并发作业数" : "并发线程数", [
            "1",
            "2",
            "4",
            "8",
            "16",
            "32",
            "64",
          ])}
          {input("block_size", "Block 大小", [
            "1KiB",
            "4KiB",
            "16KiB",
            "64KiB",
            "1MiB",
            "4MiB",
            "16MiB",
            "64MiB",
          ])}

          {input(
            "iodepth",
            tool === "fio"
              ? "I/O 队列深度（iodepth）"
              : "异步 I/O 深度（iodepth）",
            ["1", "2", "4", "8", "16", "32", "64"],
          )}
        </div>
      </div>
      <div className="performance-config-section">
        <h4>数据规模</h4>
        <div className="form-grid">
          <label>
            数据量设置
            <select
              value={sizeMode}
              onChange={(e) => onSizeMode(e.target.value)}
            >
              <option value="files">每文件大小 × 文件数量</option>
              <option value="total">总大小 ÷ 文件数量</option>
            </select>
          </label>
          {input(
            sizeMode === "files" ? "file_size" : "total_size",
            sizeMode === "files" ? "每文件大小" : "总文件大小",
            ["4KiB", "1MiB", "256MiB", "1GiB"],
          )}
          {input("file_count", "文件总数量", ["1", "4", "16", "100"])}
        </div>
      </div>
      <div className="performance-config-section">
        <h4>运行轮次</h4>
        <p className="muted">每个场景按所选轮次运行，成功轮次取平均值。</p>
        <div className="performance-rounds">
          {input("rounds", "测量轮次", ["1", "3", "5"])}{" "}
        </div>
      </div>
    </section>
  );
}
