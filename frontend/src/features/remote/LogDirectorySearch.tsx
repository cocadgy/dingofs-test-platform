import { useState } from "react";
import { useRemoteSession } from "./useRemoteSession";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { LogLoading } from "./LogLoading";
import type { SearchHit } from "./types";

function highlighted(text: string, keyword: string, sensitive: boolean) {
  if (!keyword) return text;
  const source = sensitive ? text : text.toLocaleLowerCase();
  const needle = sensitive ? keyword : keyword.toLocaleLowerCase();
  const parts: React.ReactNode[] = [];
  let start = 0;
  while (start < text.length) {
    const found = source.indexOf(needle, start);
    if (found < 0) break;
    parts.push(text.slice(start, found), <mark key={found}>{text.slice(found, found + keyword.length)}</mark>);
    start = found + keyword.length;
  }
  parts.push(text.slice(start));
  return parts;
}

export function LogDirectorySearch({ clusterId, serviceId, fileUrl }: {
  clusterId: string; serviceId: string; fileUrl: (name: string) => string;
}) {
  const [keyword, setKeyword] = useState("");
  const [sensitive, setSensitive] = useState(false);
  const [searched, setSearched] = useState<{ keyword: string; sensitive: boolean }>();
  const remote = useRemoteSession();
  const result = remote.session?.state === "succeeded" ? remote.session.result : undefined;
  const groups = new Map<string, SearchHit[]>();
  const resultUrl = (name: string) => {
    const query = new URLSearchParams({ search: searched?.keyword || "", match: name, case: searched?.sensitive ? "1" : "0" });
    return `${fileUrl(name).split("?")[0]}?${query}`;
  };
  for (const hit of result?.hits || []) groups.set(hit.name, [...(groups.get(hit.name) || []), hit]);
  return <section className="panel log-directory-search">
    <h2>搜索当前目录日志</h2>
    <form onSubmit={event => {
      event.preventDefault();
      if (!keyword.trim()) return;
      setSearched({ keyword, sensitive });
      void remote.start({ kind: "search", cluster_id: clusterId, service_id: serviceId, keyword, case_sensitive: sensitive });
    }}>
      <label>关键词 <input aria-label="日志搜索关键词" value={keyword} maxLength={200} onChange={event => setKeyword(event.target.value)} placeholder="输入错误码或文字" /></label>
      <label><input type="checkbox" checked={sensitive} onChange={event => setSensitive(event.target.checked)} />区分大小写</label>
      <button className="primary" type="submit" disabled={!keyword.trim() || remote.active}>搜索</button>
      {remote.active && <button type="button" onClick={remote.close}>取消搜索</button>}
    </form>
    <p className="muted">搜索当前目录的日志文本文件；不进入子目录，跳过压缩和二进制文件。每文件最多扫描前 1 MiB，最多扫描 200 个文件、16 MiB，总命中上限 200 条。</p>
    <RemoteSessionStatus remote={remote} />
    {remote.active && <LogLoading label="正在搜索日志…" />}
    {remote.active && remote.session?.result?.progress && <p role="status">已扫描 {remote.session.result.progress.scanned_files} 个文件，找到 {remote.session.result.progress.hits} 处匹配…</p>}
    {result && searched && <>
      <p role="status">已扫描 {result.scanned_files || 0} 个文件、{result.scanned_bytes || 0} 字节；跳过 {result.skipped_files || 0} 个文件；找到 {result.hits?.length || 0} 处匹配。{result.truncated ? `结果不完整（${result.reason || "达到扫描上限"}）。` : "搜索完成。"}</p>
      {Array.from(groups, ([name, hits]) => <div className="log-search-group" key={name}>
        <h3><a href={resultUrl(name)} target="_blank" rel="noopener noreferrer">{name}</a> <small>{hits.length} 处</small></h3>
        {hits.map(hit => <div className="log-search-hit" key={`${name}:${hit.line}`}>
          <a href={resultUrl(name)} target="_blank" rel="noopener noreferrer">打开查询结果</a>
          <pre>{hit.before.map((line, i) => <div key={`b${i}`} className="muted">{line}</div>)}<div>{highlighted(hit.text, searched.keyword, searched.sensitive)}</div>{hit.after.map((line, i) => <div key={`a${i}`} className="muted">{line}</div>)}</pre>
        </div>)}
      </div>)}
    </>}
  </section>;
}
