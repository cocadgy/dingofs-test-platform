import { useEffect, useRef, useState } from "react";
import { BadouMascot } from "../../components/BadouMascot";

type Progress = { completed_files: number; total_files: number; scanned_bytes: number; hits: number };
export function LogSearchProgress({ active, state, progress, onCancel }: {
  active: boolean; state?: string; progress?: Progress; onCancel?: () => void;
}) {
  const wasActive = useRef(false);
  const lastProgress = useRef<Progress | undefined>(undefined);
  if (active && !progress && !wasActive.current) lastProgress.current = undefined;
  if (progress) lastProgress.current = progress;
  const [showComplete, setShowComplete] = useState(false);
  useEffect(() => {
    if (active) {
      wasActive.current = true;
      setShowComplete(false);
      return;
    }
    const counts = lastProgress.current;
    if (wasActive.current && state === "succeeded" && counts && counts.completed_files >= counts.total_files) {
      wasActive.current = false;
      setShowComplete(true);
      const timer = window.setTimeout(() => setShowComplete(false), 600);
      return () => window.clearTimeout(timer);
    }
    wasActive.current = false;
    setShowComplete(false);
  }, [active, state]);
  if (!active && !showComplete) return null;
  const current = progress || lastProgress.current;
  const total = current?.total_files || 0;
  const completed = showComplete ? total : Math.min(current?.completed_files || 0, total);
  return <div className="resource-execution-indicator log-search-indicator" role="status" aria-label="日志搜索中">
    <BadouMascot animated size="large" />
    <strong>{showComplete ? "搜索完成" : "正在搜索日志"}</strong>
    <progress aria-label="搜索进度" max={total || 1} value={showComplete ? total || 1 : total ? completed : undefined} />
    <span>{showComplete ? "100%" : total ? `已完成 ${completed} / ${total} 个文件（${Math.round(completed / total * 100)}%）` : "正在统计日志文件…"}</span>
    {active && onCancel && <button type="button" onClick={onCancel}>取消搜索</button>}
  </div>;
}
