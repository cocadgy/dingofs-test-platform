import { useEffect, useState } from "react";

export type BatchChoice = { key: string; label: string; eligible: (id: string) => boolean };
export function useBatchSelection(ids: string[], busy: boolean) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const valid = new Set(ids);
  const picked = [...selected].filter(id => valid.has(id));
  useEffect(() => { if (busy) setSelected(new Set()); }, [busy]);
  function toggle(targets: string[]) {
    setSelected(previous => {
      const next = new Set([...previous].filter(id => valid.has(id)));
      const remove = targets.every(id => next.has(id));
      for (const id of targets) remove ? next.delete(id) : next.add(id);
      return next;
    });
  }
  return { picked, toggle, clear: () => setSelected(new Set()),
    checked: (targets: string[]) => targets.length > 0 && targets.every(id => picked.includes(id)) };
}
export function BatchActions({ picked, choices, disabled, onAction, onClear }: {
  picked: string[]; choices: BatchChoice[]; disabled: boolean;
  onAction: (action: string, ids: string[]) => void; onClear: () => void;
}) {
  return <div className="resource-inventory-actions" aria-label="勾选批量操作">
    <strong>已选择 {picked.length} 项</strong>
    {choices.map(choice => {
      const invalid = picked.filter(id => !choice.eligible(id)).length;
      return <button key={choice.key} type="button"
        disabled={disabled || !picked.length || invalid > 0}
        title={invalid ? `所选项中有 ${invalid} 项状态不允许此操作，请调整选择或刷新状态` : choice.label}
        onClick={() => onAction(choice.key, picked)}>{choice.label}</button>;
    })}
    <button type="button" disabled={disabled || !picked.length} onClick={onClear}>清空选择</button>
    <small>全选仅作用于当前筛选结果；不可执行的操作会禁用。</small>
  </div>;
}
