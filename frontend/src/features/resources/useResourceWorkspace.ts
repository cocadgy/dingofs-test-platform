import { requestId } from "./requestId";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import {
  pendingStates,
  type Parameters,
  type ResourceAction,
  type ResourceOperation,
  type ResourceSnapshot,
} from "./types";


export type Execute = (
  action: ResourceAction,
  values: Parameters,
  onSubmitted?: () => void,
  onAccepted?: (operation: ResourceOperation) => void,
  options?: { autoCreateFromPlan?: boolean },
) => Promise<void>;
export function useResourceWorkspace({
  id,
  name,
  revision,
  canManage,
}: {
  id: string;
  name: string;
  revision: number;
  canManage: boolean;
}) {
  const [snapshot, setSnapshot] = useState<ResourceSnapshot>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [operation, setOperation] = useState<ResourceOperation>();
  const live = useRef(false);
  const executing = useRef(false);
  const completed = useRef("");
  const refreshedCreations = useRef(new Set<string>());
  const loadSequence = useRef(0);
  const operationVersion = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    const version = operationVersion.current;
    const isCurrent = () => live.current && sequence === loadSequence.current;
    setLoading(true);
    try {
      const next = await api<ResourceSnapshot>(
        `/clusters/${encodeURIComponent(id)}/resources`,
      );
      // A slower snapshot must not undo a newer refresh or operation update.
      if (isCurrent() && version === operationVersion.current) {
        setSnapshot(next);
        setOperation((current) =>
          current
            ? next.operations.find((item) => item.id === current.id) || current
            : current,
        );
      }
    } catch (e) {
      if (isCurrent() && version === operationVersion.current)
        setError((e as Error).message);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    live.current = true;
    setSnapshot(undefined);
    setOperation(undefined);
    setError("");
    void load();
    return () => {
      live.current = false;
    };
  }, [load]);
  const accept = useCallback((next: ResourceOperation) => {
    if (!live.current) return;
    operationVersion.current++;
    setOperation(next);
    setSnapshot((current) =>
      current
        ? {
            ...current,
            operations: [
              next,
              ...current.operations.filter((item) => item.id !== next.id),
            ],
          }
        : current,
    );
  }, []);
  useEffect(() => {
    if (
      !operation ||
      pendingStates.includes(operation.state) ||
      completed.current === operation.id + operation.state
    )
      return;
    completed.current = operation.id + operation.state;
    void load();
  }, [operation, load]);
  const active =
    busy ||
    Boolean(operation && pendingStates.includes(operation.state)) ||
    Boolean(
      snapshot?.operations.some((item) => pendingStates.includes(item.state)),
    );
  async function execute(
    action: ResourceAction,
    values: Parameters,
    onSubmitted?: () => void,
    onAccepted?: (operation: ResourceOperation) => void,
    options?: { autoCreateFromPlan?: boolean },
  ) {
    if (!canManage || active || executing.current || !snapshot) return;
    const target = Object.fromEntries(
      Object.entries(values)
        .filter(
          ([key]) =>
            action.fields.find((field) => field.key === key)?.type !==
            "password",
        )
        .map(([key, value]) => [
          key,
          key === "storage_profile_id"
            ? `${snapshot.storage_profiles?.find((item) => item.id === value)?.name || value} (${value})`
            : key === "resource_id"
              ? `${snapshot.resources.find((item) => item.id === value)?.name || value} (${value})`
              : key === "machine_id"
                ? `${snapshot.machines.find((item) => item.id === value)?.name || value} (${value})`
                : value,
        ]),
    );
    if (
      action.mutating &&
      !(
        options?.autoCreateFromPlan &&
        action.action === "cache.create" &&
        typeof values.plan_id === "string" &&
        values.plan_id.length > 0
      ) &&
      !window.confirm(
        `确认在集群「${name}」执行「${action.label}」？\n目标与参数：\n${JSON.stringify(target, null, 2)}`,
      )
    )
      return;
    executing.current = true;
    setBusy(true);
    setError("");
    onSubmitted?.();
    try {
      const next = await api<ResourceOperation>(
        `/clusters/${encodeURIComponent(id)}/resource-operations`,
        "POST",
        {
          base_revision: revision,
          request_id: requestId(),
          action: action.action,
          parameters: values,
          confirmed: action.mutating,
        },
      );
      accept(next);
      onAccepted?.(next);
    } catch (e) {
      if (live.current)
        setError(
          e instanceof ApiError &&
            [400, 401, 403, 404, 409, 422, 429].includes(e.status)
            ? `${e.message}。本次请求未创建新任务。`
            : `${(e as Error).message}。请求可能已发出，请先刷新已保存记录并核实远端状态，再决定是否重新操作。`,
        );
    } finally {
      executing.current = false;
      if (live.current) setBusy(false);
    }
  }
  useEffect(() => {
    if (
      !canManage ||
      active ||
      executing.current ||
      !operation ||
      !(
        (operation.action === "cache.create" &&
          operation.state === "succeeded") ||
        (["cache.stop", "cache.delete", "cache.delete_batch", "cache.leave", "cache.unlock", "cache.weight"].includes(
          operation.action,
        ) &&
          ["succeeded", "failed", "cancelled", "interrupted"].includes(
            operation.state,
          ))
      )
    )
      return;
    const key = `${id}:${operation.id}`;
    if (refreshedCreations.current.has(key)) return;
    const query = snapshot?.catalog.find(
      (item) => item.action === "cache.list",
    );
    if (!query) return;
    // One query per completed cache mutation, including StrictMode effect replay.
    // Only observed completion triggers this; opening historical records does not.
    refreshedCreations.current.add(key);
    void execute(query, {});
  }, [id, operation, canManage, active, snapshot, execute]);
  const operations = useMemo(() => {
    const records = operation
      ? [
          operation,
          ...(snapshot?.operations || []).filter(
            (item) => item.id !== operation.id,
          ),
        ]
      : [...(snapshot?.operations || [])];
    return records.sort(
      (a, b) =>
        (Date.parse(b.created_at || "") || 0) -
        (Date.parse(a.created_at || "") || 0),
    );
  }, [operation, snapshot?.operations]);
  function refresh() {
    setError("");
    void load();
  }
  return {
    snapshot,
    error,
    loading,
    active,
    operations,
    execute,
    accept,
    refresh,
  };
}
