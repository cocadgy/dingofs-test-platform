import { useEffect, useMemo, useRef, useState } from "react";
import {
  cacheMemberOptions,
  type CacheMemberOption,
} from "./cacheMemberOptions";
import {
  pendingStates,
  type ResourceOperation,
  type ResourceSnapshot,
} from "./types";
import type { Execute } from "./useResourceWorkspace";

export function mergeCacheDeletions(
  operations: ResourceOperation[],
  deletedAt = new Map<string, number>(),
) {
  let next = deletedAt;
  for (const item of operations) {
    const memberIds =
      item.action === "cache.delete_batch"
        ? (item.result?.steps || [])
            .filter((step) => step.failed === false)
            .map((step) => step.member_id)
        : item.action === "cache.delete" && item.state === "succeeded"
          ? [item.payload?.member_id]
          : [];
    for (const memberId of memberIds) {
      if (typeof memberId !== "string") continue;
      const time = Date.parse(item.created_at || "") || 0;
      if ((next.get(memberId) ?? -1) >= time) continue;
      if (next === deletedAt) next = new Map(deletedAt);
      next.set(memberId, time);
    }
  }
  return next;
}

export function useCacheMemberListing(
  snapshot: ResourceSnapshot,
  execute: Execute,
) {
  const latest = snapshot.operations.find(
    (item) => item.action === "cache.list",
  );
  const [listing, setListing] = useState<{
    loading: boolean;
    operation?: ResourceOperation;
    error?: string;
  }>({ loading: false, operation: latest });
  const sequence = useRef(0);
  const refreshing = useRef(false);
  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );
  const retained =
    snapshot.operations.find((item) => item.id === listing.operation?.id) ||
    listing.operation;
  const operation =
    latest &&
    (!retained ||
      (Date.parse(latest.created_at || "") || 0) >
        (Date.parse(retained.created_at || "") || 0))
      ? latest
      : retained;
  useEffect(() => {
    if (operation)
      setListing((previous) =>
        previous.operation === operation
          ? previous
          : { ...previous, operation },
      );
  }, [operation]);
  // Retain successful deletions even when they leave the recent history window.
  const [deletedAt, setDeletedAt] = useState(new Map<string, number>());
  const knownDeletions = useMemo(() => {
    return mergeCacheDeletions(snapshot.operations, deletedAt);
  }, [snapshot.operations, deletedAt]);
  useEffect(() => {
    if (knownDeletions !== deletedAt) setDeletedAt(knownDeletions);
  }, [knownDeletions, deletedAt]);
  const pending =
    listing.loading ||
    Boolean(operation && pendingStates.includes(operation.state));
  const { options, error } = useMemo(() => {
    let options: CacheMemberOption[] = [];
    let error = listing.error || "";
    if (operation && !pending && !error) {
      if (operation.state === "succeeded") {
        try {
          const queriedAt = Date.parse(operation.created_at || "") || 0;
          options = cacheMemberOptions(operation).filter(
            (member) => (knownDeletions.get(member.id) ?? -1) < queriedAt,
          );
        } catch (cause) {
          error = (cause as Error).message;
        }
      } else error = operation.message || "缓存成员列表获取失败，请刷新重试。";
    }
    return { options, error };
  }, [operation, pending, listing.error, knownDeletions]);
  async function refresh() {
    if (refreshing.current) return;
    refreshing.current = true;
    const current = ++sequence.current;
    setListing({ loading: true });
    try {
      const action = snapshot.catalog.find(
        (item) => item.action === "cache.list",
      );
      if (!action) throw new Error("当前集群不支持查询缓存成员列表。");
      let accepted: ResourceOperation | undefined;
      await execute(action, {}, undefined, (next) => {
        accepted = next;
      });
      if (current === sequence.current)
        setListing(
          accepted
            ? { loading: false, operation: accepted }
            : { loading: false, error: "未能获取缓存成员列表，请刷新重试。" },
        );
    } catch (cause) {
      if (current === sequence.current)
        setListing({ loading: false, error: (cause as Error).message });
    } finally {
      refreshing.current = false;
    }
  }
  return { operation, options, error, pending, refresh };
}
