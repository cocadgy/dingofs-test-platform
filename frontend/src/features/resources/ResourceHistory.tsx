import { memo, useMemo, useState } from "react";
import { ResourceOperationView } from "./ResourceOperationView";
import {
  pendingStates,
  stateLabels,
  type ResourceAction,
  type ResourceOperation,
} from "./types";
import { actionGroup, type ResourceArea } from "./workspace";

export function ResourceHistory({
  area,
  selectedGroup,
  operations,
  catalog,
  canManage,
  userId,
  onChange,
  onOpenLog,
  onShowHistory,
  historySearch,
  setHistorySearch,
  historyState,
  setHistoryState,
}: {
  area: ResourceArea;
  selectedGroup: string;
  operations: ResourceOperation[];
  catalog: ResourceAction[];
  canManage: boolean;
  userId?: string;
  onChange: (operation: ResourceOperation) => void;
  onOpenLog?: (operation: ResourceOperation, filename: string) => void;
  onShowHistory: () => void;
  historySearch: string;
  setHistorySearch: (value: string) => void;
  historyState: string;
  setHistoryState: (value: string) => void;
}) {
  const recent = operations.find(
    (item) => actionGroup(item.action) === selectedGroup,
  );
  const historyMatches = useMemo(() => {
    if (area !== "history") return [];
    const search = historySearch.toLowerCase().trim();
    return operations.filter((item) => {
      if (historyState && item.state !== historyState) return false;
      if (!search) return true;
      const label =
        catalog.find((entry) => entry.action === item.action)?.label ||
        item.action;
      return `${label} ${item.id} ${item.machine_name || ""} ${JSON.stringify(item.payload || {})}`
        .toLowerCase()
        .includes(search);
    });
  }, [area, operations, catalog, historyState, historySearch]);
  return (
    <section
      className="resource-history"
      aria-label={area === "history" ? "资源操作记录" : "当前结果"}
    >
      <div className="resource-result-heading">
        <div>
          <h3>{area === "history" ? "操作记录" : "最近一次结果"}</h3>
          <p className="muted">
            {area === "history"
              ? "查看已保存的执行记录，展开记录了解详情。"
              : "仅展示当前功能的最近一次执行结果。"}
          </p>
        </div>
        {area !== "history" && (
          <button type="button" onClick={onShowHistory}>
            查看全部记录
          </button>
        )}
      </div>
      {area === "history" && (
        <div className="resource-history-filters">
          <label>
            搜索操作记录
            <input
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              placeholder="操作名称、目标或机器"
            />
          </label>
          <label>
            操作状态
            <select
              value={historyState}
              onChange={(e) => setHistoryState(e.target.value)}
            >
              <option value="">全部状态</option>
              {[
                "pending",
                "running",
                "needs_password",
                "needs_trust",
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                "unknown",
                "partial",
              ].map((state) => (
                <option key={state} value={state}>
                  {stateLabels[state] || state}
                </option>
              ))}
            </select>
          </label>
          <span>{historyMatches.length} 条记录</span>
        </div>
      )}
      {area === "history"
        ? !historyMatches.length && (
            <p className="resource-empty">
              {operations.length ? "没有匹配的操作记录" : "暂无操作记录。"}
            </p>
          )
        : !recent && (
            <p className="resource-empty">
              暂无当前功能的执行结果，选择操作后点击执行。
            </p>
          )}
      {operations.map((item, index) => {
        const label =
          catalog.find((entry) => entry.action === item.action)?.label ||
          item.action;
        return (
          <HistoryEntry
            key={item.id}
            item={item}
            label={label}
            newest={index === 0}
            visible={
              area === "history"
                ? historyMatches.includes(item)
                : item.id === recent?.id
            }
            defaultOpen={
              area !== "history" || item.id === historyMatches[0]?.id
            }
            context={`${area}:${selectedGroup}`}
            canManage={
              canManage && (!item.creator_id || item.creator_id === userId)
            }
            onChange={onChange}
            onOpenLog={onOpenLog}
          />
        );
      })}
    </section>
  );
}

// Keep active operation observers mounted even when their result is not visible.
// Completed hidden rows and collapsed result bodies should create no result DOM.
const HistoryEntry = memo(function HistoryEntry({
  item,
  label,
  newest,
  visible,
  defaultOpen,
  context,
  canManage,
  onChange,
  onOpenLog,
}: {
  item: ResourceOperation;
  label: string;
  newest: boolean;
  visible: boolean;
  defaultOpen: boolean;
  context: string;
  canManage: boolean;
  onChange: (operation: ResourceOperation) => void;
  onOpenLog?: (operation: ResourceOperation, filename: string) => void;
}) {
  const scope = `${context}:${visible}:${defaultOpen}`;
  const [expanded, setExpanded] = useState<{ scope: string; open: boolean }>();
  const open = expanded?.scope === scope ? expanded.open : defaultOpen;
  const showDetails = visible && open;
  const active = pendingStates.includes(item.state);
  if (!visible && !active) return null;
  return (
    <details
      className="resource-history-entry"
      hidden={!visible}
      open={open}
      onToggle={(event) => {
        if (event.target === event.currentTarget)
          setExpanded({ scope, open: event.currentTarget.open });
      }}
    >
      <summary>
        <strong>{label}</strong>
        <time dateTime={item.created_at}>
          {item.created_at
            ? new Date(item.created_at).toLocaleString("zh-CN", {
                hour12: false,
              })
            : "时间未记录"}
        </time>
        <span
          className={`badge ${["failed", "interrupted", "unknown", "partial"].includes(item.state) ? "error" : ""}`}
        >
          {stateLabels[item.state] || item.state}
        </span>
        {newest && <small>最新记录</small>}
      </summary>
      {(showDetails || active) && (
        <ResourceOperationView
          summarized
          operation={item}
          label={label}
          canManage={canManage}
          onChange={onChange}
          onOpenLog={canManage ? onOpenLog : undefined}
          renderDetails={showDetails}
        />
      )}
    </details>
  );
});
