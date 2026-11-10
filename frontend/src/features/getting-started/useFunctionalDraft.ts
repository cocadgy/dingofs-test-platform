import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { GuidedConfiguration } from "../functional/types";

export type FunctionalDraft = {
  id:string;revision:number;name:string;step:number;state:string;
  configuration:GuidedConfiguration;updated_at?:string;
};
const isGuided = (row:FunctionalDraft) =>
  row.state === "draft" && row.configuration?.kind === "existing-environments" &&
  row.configuration?.version === 2;

export function useFunctionalDraft(userId:string, requestedId:string) {
  const [draft,setDraft] = useState<FunctionalDraft>();
  const [suggested,setSuggested] = useState<FunctionalDraft[]>([]);
  const [restored,setRestored] = useState<FunctionalDraft>();
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState("");
  const current = useRef<FunctionalDraft|undefined>(undefined);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const restore = useCallback(async (id:string) => {
    const row = await api<FunctionalDraft>(`/functional/drafts/${encodeURIComponent(id)}`);
    if (!isGuided(row)) throw new Error("草稿不是未提交的已有环境引导，请从原六步向导继续");
    current.current = row;
    setDraft(row);
    setRestored(row);
    setSuggested([]);
    setError("");
    return row;
  }, []);

  useEffect(() => {
    let live = true;
    current.current = undefined;
    setDraft(undefined);
    setRestored(undefined);
    setLoading(true);
    (requestedId
      ? restore(requestedId).then(() => undefined)
      : api<FunctionalDraft[]>("/functional/drafts").then(rows => {
          if (live) setSuggested(rows.filter(isGuided));
        }))
      .catch(reason => { if (live) setError((reason as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [requestedId,userId,restore]);

  const save = useCallback((configuration:GuidedConfiguration, step:number) => {
    const pending = queue.current.catch(() => undefined).then(async () => {
      const previous = current.current;
      const payload = {name:configuration.name.trim() || "未命名功能测试",
        step,configuration,...(previous ? {revision:previous.revision} : {})};
      try {
        const row = await api<FunctionalDraft>(
          previous ? `/functional/drafts/${encodeURIComponent(previous.id)}` : "/functional/drafts",
          previous ? "PUT" : "POST",payload);
        current.current = row;
        setDraft(row);
        setError("");
        return row;
      } catch (reason) {
        const message = (reason as Error).message;
        setError(message.includes("409") || message.includes("冲突") || message.includes("修改")
          ? "草稿已在其他页面修改。请重新载入，当前内容不会覆盖较新版本。" : message);
        throw reason;
      }
    });
    queue.current = pending;
    return pending;
  }, []);

  return {draft,suggested,restored,loading,error,setError,restore,save,
    dismissSuggestions:() => setSuggested([])};
}
