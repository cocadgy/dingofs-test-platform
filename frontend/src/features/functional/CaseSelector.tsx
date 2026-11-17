import { useEffect, useRef, useState } from "react";
import { Case, moduleLabels } from "./types";
function Check({
  checked,
  partial,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { partial?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = !!partial;
  }, [partial]);
  return <input {...props} ref={ref} type="checkbox" checked={checked} />;
}
export function CaseSelector({
  modules,
  selected,
  onChange,
}: {
  modules: Record<string, Case[]>;
  selected: Record<string, string[]>;
  onChange: (value: Record<string, string[]>) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlySelected, setOnlySelected] = useState(false);
  const count = Object.values(selected).reduce((n, rows) => n + rows.length, 0);
  function toggle(module: string, paths: string[], include: boolean) {
    const next = new Set(selected[module] || []);
    paths.forEach((path) => (include ? next.add(path) : next.delete(path)));
    onChange({ ...selected, [module]: [...next].sort() });
  }
  return (
    <section className="functional-card">
      <h2>
        选择用例 <small>已选 {count} 项</small>
      </h2>
      <div className="functional-toolbar">
        <input
          type="search"
          aria-label="搜索用例"
          placeholder="搜索用例名称、路径、说明或模块"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="functional-check">
          <input
            type="checkbox"
            checked={onlySelected}
            onChange={(e) => setOnlySelected(e.target.checked)}
          />
          只看已选
        </label>
        <button disabled={!count} onClick={() => onChange({})}>
          清空选择
        </button>
      </div>
      <div className="functional-tree">
        {Object.entries(modules).map(([module, cases]) => {
          const chosen = selected[module] || [];
          const visible = cases.filter(
            (c) =>
              (!onlySelected || chosen.includes(c.path)) &&
              `${module} ${moduleLabels[module] || ""} ${c.name} ${c.path} ${c.description || ""}`
                .toLowerCase()
                .includes(query.toLowerCase()),
          );
          if (!visible.length) return null;
          return (
            <details
              key={module + Boolean(query || onlySelected)}
              open={query || onlySelected ? true : undefined}
            >
              <summary>
                <Check
                  aria-label={`选择 ${module} 全部用例`}
                  checked={chosen.length === cases.length}
                  partial={chosen.length > 0 && chosen.length < cases.length}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() =>
                    toggle(
                      module,
                      cases.map((c) => c.path),
                      chosen.length !== cases.length,
                    )
                  }
                />
                <strong>{moduleLabels[module] || module}</strong>
                {moduleLabels[module] && <small>{module}</small>}
                <span>
                  {chosen.length}/{cases.length}
                </span>
              </summary>
              {visible.map((c) => (
                <label key={c.path}>
                  <Check
                    checked={chosen.includes(c.path)}
                    onChange={(e) => toggle(module, [c.path], e.target.checked)}
                  />
                  <span>
                    {c.name}
                    <small>
                      {c.description || c.path}
                      {c.run_level ? ` · ${c.run_level}` : ""}
                    </small>
                    {c.description && <small>{c.path}</small>}
                  </span>
                </label>
              ))}
            </details>
          );
        })}
        {Object.entries(modules).every(
          ([module, cases]) =>
            !cases.some(
              (c) =>
                (!onlySelected || (selected[module] || []).includes(c.path)) &&
                `${module} ${moduleLabels[module] || ""} ${c.name} ${c.path} ${c.description || ""}`
                  .toLowerCase()
                  .includes(query.toLowerCase()),
            ),
        ) && (
          <p className="functional-empty">没有匹配用例，试试调整搜索条件。</p>
        )}
      </div>
    </section>
  );
}
