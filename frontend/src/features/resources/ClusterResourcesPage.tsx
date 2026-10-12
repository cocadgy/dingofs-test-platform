import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ClusterDetailData } from "../clusters/types";
import { ClusterResources } from "./ClusterResources";

export function resourceRoute(hash: string) {
  const match = hash.match(/^#\/clusters\/([^/]+)\/resources$/);
  try {
    return match ? decodeURIComponent(match[1]) : undefined;
  } catch {
    return undefined;
  }
}

export function ClusterResourcesPage({
  id,
  admin,
  userId,
}: {
  id: string;
  admin: boolean;
  userId?: string;
}) {
  const [cluster, setCluster] = useState<ClusterDetailData>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setCluster(undefined);
    setError("");
    api<ClusterDetailData>(`/clusters/${encodeURIComponent(id)}`)
      .then((value) => {
        if (active) setCluster(value);
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      });
    return () => {
      active = false;
    };
  }, [id]);
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / CLUSTER RESOURCES</p>
          <h1>资源管理{cluster ? ` · ${cluster.external_name}` : ""}</h1>
          <p className="muted">管理当前集群的文件系统、缓存组和挂载点。</p>
        </div>
        <a className="button" href={`#/clusters/${encodeURIComponent(id)}`}>
          返回集群详情
        </a>
      </header>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : !cluster ? (
        <p>正在读取集群信息…</p>
      ) : (
        <ClusterResources
          key={id}
          id={id}
          name={cluster.external_name}
          revision={cluster.revision}
          userId={userId}
          admin={admin}
          canManage={
            (admin || (!!userId && cluster.creator_id === userId)) &&
            !cluster.archived &&
            cluster.binding_state === "verified"
          }
        />
      )}
    </>
  );
}
