import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { OperationAuthDialog } from "./OperationAuthDialog";
import { type Operation } from "./types";

export function ClusterTopology({
  id,
  revision,
  canOperate = true,
}: {
  id: string;
  revision: number;
  canOperate?: boolean;
}) {
  const [operation, setOperation] = useState<Operation>();
  const [content, setContent] = useState<string>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState("");
  const live = useRef(true);
  const accept = useCallback((next: Operation) => {
    if (!live.current) return;
    setOperation(next);
    if (next.state === "succeeded") {
      setContent(String(next.result?.stdout ?? ""));
      setUpdated(new Date().toLocaleString());
    }
  }, []);
  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      accept(
        await api<Operation>(`/clusters/${id}/topology`, "POST", {
          base_revision: revision,
        }),
      );
    } catch (e) {
      if (live.current) setError((e as Error).message);
    } finally {
      if (live.current) setBusy(false);
    }
  }, [id, revision, accept]);
  useEffect(() => {
    live.current = true;
    if (canOperate) refresh();
    else
      api<{ stdout: string | null; collected_at: string | null }>(
        `/clusters/${id}/topology`,
      )
        .then((r) => {
          if (live.current) {
            setContent(r.stdout ?? undefined);
            setUpdated(
              r.collected_at ? new Date(r.collected_at).toLocaleString() : "",
            );
          }
        })
        .catch((e) => {
          if (live.current) setError(e.message);
        });
    return () => {
      live.current = false;
    };
  }, [refresh, canOperate, id]);
  const active =
    busy ||
    (!!operation &&
      ["pending", "running", "needs_password"].includes(operation.state));
  return (
    <section className="panel">
      <div className="actions">
        <h2>topology.yaml</h2>
        <button disabled={active || !canOperate} onClick={refresh}>
          刷新 topology.yaml
        </button>
      </div>
      <p className="muted">
        来自当前集群的 dingo config show，只读展示。
        {updated && `最近成功读取：${updated}`}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {operation && (
        <OperationAuthDialog operation={operation} onChange={accept} />
      )}
      {operation &&
        ["failed", "interrupted", "cancelled"].includes(operation.state) &&
        content !== undefined && <p>本次读取未成功，保留上次读取内容。</p>}
      <pre className="cluster-raw">
        {content === undefined
          ? "尚未读取 topology.yaml"
          : content || "命令未返回内容"}
      </pre>
    </section>
  );
}
