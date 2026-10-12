import { useEffect } from "react";
import { useRemoteSession } from "./useRemoteSession";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { LogLoading } from "./LogLoading";

export function LogSearchResultPage({ clusterId, serviceId, fileName, keyword, caseSensitive, backUrl }: {
  clusterId: string; serviceId: string; fileName: string; keyword: string; caseSensitive: boolean; backUrl: string;
}) {
  const remote = useRemoteSession();
  useEffect(() => {
    if (keyword.trim() && keyword.length <= 200 && fileName) {
      void remote.start({ kind: "search", cluster_id: clusterId, service_id: serviceId, keyword, case_sensitive: caseSensitive });
    }
    // The route is stable for the lifetime of this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterId, serviceId, fileName, keyword, caseSensitive]);
  const result = remote.session?.state === "succeeded" ? remote.session.result : undefined;
  const hits = result?.hits?.filter(hit => hit.name === fileName) || [];
  return <>
    <header className="page-header remote-header"><div><p className="eyebrow">LOG SEARCH</p><h1>{fileName} · 查询结果</h1><p>关键词：{keyword}</p></div><a className="button" href={backUrl}>返回日志列表</a></header>
    <section className="panel">
      {!keyword.trim() || keyword.length > 200 || !fileName ? <p role="alert">查询参数无效</p> : <>
        <RemoteSessionStatus remote={remote} />
        {remote.active && <LogLoading label="正在读取日志查询结果…" />}
        {remote.active && <button onClick={remote.close}>取消查询</button>}
        {result && <>
          <p role="status">本文件匹配 {hits.length} 条。{result.truncated && "搜索达到上限，结果可能不完整。"}</p>
          {hits.length ? <div className="log-search-results">{hits.map((hit, index) => <pre key={`${hit.name}:${hit.line}:${index}`}>{hit.text}</pre>)}</div> : <p className="empty">没有匹配结果</p>}
        </>}
      </>}
    </section>
  </>;
}
