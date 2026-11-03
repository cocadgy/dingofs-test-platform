import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";

type Tag = { name: string; updated_at: string; digest: string; available: boolean };
type Page = { items: Tag[]; count: number; next_page: number | null };
export function CacheTagSelector({ tag, digest, onChange }: {
  tag: string; digest: string; onChange: (tag: string, digest: string) => void;
}) {
  const [items, setItems] = useState<Tag[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  async function load(page: number, term: string) {
    const current = ++generation.current;
    setBusy(true); setError("");
    try {
      const response = await api<Page>("/cache-image-tags?page=" + page + "&search=" + encodeURIComponent(term));
      if (current !== generation.current) return;
      setItems(previous => {
        const merged = new Map((page === 1 ? [] : previous).map(item => [item.name, item]));
        response.items.forEach(item => merged.set(item.name, item));
        return [...merged.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      });
      setNext(response.next_page);
    } catch (cause) {
      if (current === generation.current) setError((cause as Error).message);
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  useEffect(() => { void load(1, ""); return () => { generation.current++; }; }, []);
  return <div className="guided-tag-selector">
    <label>搜索 TAG<input value={search} onChange={event => setSearch(event.target.value)} placeholder="例如 main、v5.2、fe4384a" /></label>
    <div className="getting-started-actions"><button type="button" onClick={() => { setQuery(search.trim()); void load(1, search.trim()); }}>搜索 TAG</button></div>
    <label>镜像 TAG<select value={tag} disabled={busy} onChange={event => {
      const selected = items.find(item => item.name === event.target.value);
      onChange(selected?.name || "", selected?.digest || "");
    }}>
      <option value="">请选择 TAG（最新更新在最上方）</option>
      {items.map(item => <option key={item.name} value={item.name} disabled={!item.available}>
        {item.name} · {new Date(item.updated_at).toLocaleString("zh-CN", { hour12: false })}{!item.available ? " · 不支持 Linux amd64" : ""}
      </option>)}
      {tag && !items.some(item => item.name === tag) && <option value={tag}>{tag}（已选择，摘要已固定）</option>}
    </select></label>
    {busy && <p role="status">正在获取 TAG…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => void load(1, query)}>重试</button></p>}
    {!busy && !error && !items.length && <p>没有匹配的 TAG。</p>}
    {next && <button type="button" disabled={busy} onClick={() => void load(next, query)}>加载更多 TAG</button>}
    {tag && digest && <p className="muted" style={{ overflowWrap: "anywhere" }}>已固定：{tag} · {digest}</p>}
    <p className="muted">这里只查询版本。选择机器并确认后，平台才下载、提取并分发程序。首次下载可能需要数分钟；不会自动切换版本。</p>
  </div>;
}
