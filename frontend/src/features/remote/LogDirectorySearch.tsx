import { useState } from "react";
import { useRemoteSession } from "./useRemoteSession";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { LogSearchProgress } from "./LogSearchProgress";
import type { SearchHit } from "./types";
import { highlightKeyword } from "./highlightKeyword";
import { defaultSearchOptions, type SearchOptions } from "./searchOptions";


export function LogDirectorySearch({ clusterId, serviceId, fileUrl }: {
  clusterId: string; serviceId: string; fileUrl: (name: string) => string;
}) {
  const [keyword, setKeyword] = useState("");
  const [sensitive, setSensitive] = useState(false);
  const [options, setOptions] = useState<SearchOptions>(defaultSearchOptions);
  const [searched, setSearched] = useState<{ keyword: string; sensitive: boolean; options: SearchOptions }>();
  const remote = useRemoteSession();
  const result = remote.session?.state === "succeeded" ? remote.session.result : undefined;
  const groups = new Map<string, SearchHit[]>();
  const reasonText: Record<string, string> = { directory_limit: "目录条目上限", file_count_limit: "文件数上限", total_bytes_limit: "总扫描量上限", file_limit: "单文件前部上限", match_limit: "结果数上限", time_limit: "90 秒时限", line_limit: "单行长度上限", result_bytes_limit: "结果传输上限" };
  const resultUrl = (name: string) => {
    const selected = searched?.options || defaultSearchOptions;
    const query = new URLSearchParams({ search: searched?.keyword || "", match: name, case: searched?.sensitive ? "1" : "0", mode: selected.scan_mode, per_file_mb: String(selected.per_file_mb), max_files: String(selected.max_files), max_total_mb: String(selected.max_total_mb), max_hits: String(selected.max_hits) });
    return `${fileUrl(name).split("?")[0]}?${query}`;
  };
  for (const hit of result?.hits || []) groups.set(hit.name, [...(groups.get(hit.name) || []), hit]);
  return <section className="panel log-directory-search">
    <h2>搜索当前目录日志</h2>
    <form onSubmit={event => {
      event.preventDefault();
      if (!keyword.trim()) return;
      setSearched({ keyword, sensitive, options });
      void remote.start({ kind: "search", cluster_id: clusterId, service_id: serviceId, keyword, case_sensitive: sensitive, ...options });
    }}>
      <label>关键词 <input aria-label="日志搜索关键词" value={keyword} maxLength={200} onChange={event => setKeyword(event.target.value)} placeholder="输入错误码或文字" /></label>
      <label><input type="checkbox" checked={sensitive} onChange={event => setSensitive(event.target.checked)} />区分大小写</label>
      <label>扫描方式 <select aria-label="扫描方式" value={options.scan_mode} onChange={event => setOptions(previous => ({ ...previous, scan_mode: event.target.value as SearchOptions["scan_mode"] }))}><option value="prefix">按文件前部扫描</option><option value="full">全文搜索</option></select></label>
      <label>单文件前部上限 <select aria-label="单文件前部上限" disabled={options.scan_mode === "full"} value={options.per_file_mb} onChange={event => setOptions(previous => ({ ...previous, per_file_mb: Number(event.target.value) }))}>{[1, 4, 16, 64].map(value => <option key={value} value={value}>{value} MiB</option>)}</select></label>
      <label>最多文件 <select aria-label="最多文件" value={options.max_files} onChange={event => setOptions(previous => ({ ...previous, max_files: Number(event.target.value) }))}>{[50, 200, 500, 1000].map(value => <option key={value} value={value}>{value} 个</option>)}</select></label>
      <label>总扫描量 <select aria-label="总扫描量" value={options.max_total_mb} onChange={event => setOptions(previous => ({ ...previous, max_total_mb: Number(event.target.value) }))}>{[16, 64, 256, 1024].map(value => <option key={value} value={value}>{value} MiB</option>)}<option value={0}>不限</option></select></label>
      <label>最多结果 <select aria-label="最多结果" value={options.max_hits} onChange={event => setOptions(previous => ({ ...previous, max_hits: Number(event.target.value) }))}>{[50, 200, 500].map(value => <option key={value} value={value}>{value} 条</option>)}<option value={0}>不限</option></select></label>
      <button className="primary" type="submit" disabled={!keyword.trim() || remote.active}>搜索</button>
    </form>
    <p className="muted">全文搜索会读取文件的全部内容；选择“不限”仅取消对应的扫描量或结果数限制，仍受 90 秒执行时限和 3 MiB 结果传输上限约束。不进入子目录，跳过压缩和二进制文件；触及限制会显示结果不完整。</p>
    <RemoteSessionStatus remote={remote} />
    <LogSearchProgress active={remote.active} state={remote.session?.state} onCancel={remote.close} progress={remote.session?.result?.progress || (remote.session?.result?.total_files !== undefined ? { completed_files: remote.session.result.completed_files || 0, total_files: remote.session.result.total_files, scanned_bytes: remote.session.result.scanned_bytes || 0, hits: remote.session.result.hits?.length || 0 } : undefined)} />

    {result && searched && <>
      <p role="status">已扫描 {result.scanned_files || 0} 个文件、{result.scanned_bytes || 0} 字节；跳过 {result.skipped_files || 0} 个文件；找到 {result.hits?.length || 0} 处匹配。{result.truncated ? `结果不完整（${reasonText[result.reason || ""] || "达到扫描上限"}）。` : "搜索完成。"}</p>
      {Array.from(groups, ([name, hits]) => <div className="log-search-group" key={name}>
        <h3><a href={resultUrl(name)} target="_blank" rel="noopener noreferrer">{name}</a> <small>{hits.length} 处</small></h3>
        {hits.map(hit => <div className="log-search-hit" key={`${name}:${hit.line}`}>
          <a href={resultUrl(name)} target="_blank" rel="noopener noreferrer">打开查询结果</a>
          <pre>{hit.before.map((line, i) => <div key={`b${i}`} className="muted">{line}</div>)}<div>{highlightKeyword(hit.text, searched.keyword, searched.sensitive)}</div>{hit.after.map((line, i) => <div key={`a${i}`} className="muted">{line}</div>)}</pre>
        </div>)}
      </div>)}
    </>}
  </section>;
}
