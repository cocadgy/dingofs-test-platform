import { useCallback, useEffect, useRef, useState } from "react";
import { ClusterOverview, initialState } from "./ClusterOverview";
import { ClusterDetail } from "./ClusterDetail";
import { DiscoverClusters } from "./DiscoverClusters";
function route() {
  const m = location.hash.match(/^#\/clusters\/([^/]+)$/);
  try {
    return m ? decodeURIComponent(m[1]) : "";
  } catch {
    return "";
  }
}
export function ClusterPage({
  admin,
  userId,
  onDirty,
}: {
  admin: boolean;
  userId?: string;
  onDirty: (v: boolean) => void;
}) {
  const [id, setId] = useState(route),
    [state, setState] = useState(initialState),
    [discover, setDiscover] = useState(false),
    [reload, setReload] = useState(0);
  const dirty = useRef(false),
    current = useRef(id);
  const changed = useCallback(
    (v: boolean) => {
      dirty.current = v;
      onDirty(v);
    },
    [onDirty],
  );
  useEffect(() => {
    const sync = () => {
      const next = route();
      if (next === current.current) return;
      if (dirty.current && !confirm("有未保存修改，确定离开？")) {
        history.replaceState(
          null,
          "",
          current.current
            ? "#/clusters/" + encodeURIComponent(current.current)
            : "#/clusters",
        );
        return;
      }
      changed(false);
      current.current = next;
      setId(next);
      setDiscover(false);
    };
    addEventListener("hashchange", sync);
    return () => removeEventListener("hashchange", sync);
  }, [changed]);
  function navigate(next: string) {
    location.hash = next
      ? "#/clusters/" + encodeURIComponent(next)
      : "#/clusters";
  }
  function showDiscovery() {
    if (dirty.current && !confirm("有未保存修改，确定离开？")) return;
    changed(false);
    setDiscover(true);
  }
  if (discover)
    return (
      <DiscoverClusters
        admin={admin}
        userId={userId}
        onClose={() => setDiscover(false)}
        onImported={() => {
          setState(initialState);
          setDiscover(false);
          setReload((n) => n + 1);
          navigate("");
        }}
      />
    );
  return id ? (
    <ClusterDetail
      key={id}
      id={id}
      admin={admin}
      userId={userId}
      onDirty={changed}
      onBack={() => navigate("")}
      onDiscover={showDiscovery}
    />
  ) : (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / CLUSTERS</p>
          <h1>集群管理</h1>
          <p className="muted">
            按执行机器和用户发现已有集群，点击一行查看服务状态。
          </p>
        </div>
        {
          <button className="primary" onClick={showDiscovery}>
            发现集群
          </button>
        }
      </header>
      <ClusterOverview
        admin={admin}
        userId={userId}
        key={reload}
        state={state}
        onStateChange={setState}
        onOpen={navigate}
      />
    </>
  );
}
