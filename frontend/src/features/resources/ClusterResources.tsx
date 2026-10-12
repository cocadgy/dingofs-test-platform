import { BadouMascot } from "../../components/BadouMascot";
import { useState } from "react";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { ResourceNavigation } from "./ResourceNavigation";
import { ResourceHistory } from "./ResourceHistory";
import { useResourceWorkspace } from "./useResourceWorkspace";
import {
  pendingStates,
  stateLabels,
  type ResourceSection,
  type ResourceOperation,
} from "./types";
import { actionGroup, sections, type ResourceArea } from "./workspace";
import "./resources.css";

export function ClusterResources({
  id,
  name,
  revision,
  canManage,
  userId,
}: {
  id: string;
  name: string;
  revision: number;
  canManage: boolean;
  userId?: string;
  admin?: boolean;
}) {
  const [area, setArea] = useState<ResourceArea>("filesystem");
  const [groups, setGroups] = useState<Record<ResourceSection, string>>({
    filesystem: "基础操作",
    cache: "缓存组操作",
    mount: "挂载操作",
  });
  const [historySearch, setHistorySearch] = useState("");
  const [historyState, setHistoryState] = useState("");
  const {
    snapshot,
    error,
    loading,
    active,
    operations,
    execute,
    accept,
    refresh,
  } = useResourceWorkspace({ id, name, revision, canManage });
  const labelFor = (item: ResourceOperation) =>
    snapshot?.catalog.find((entry) => entry.action === item.action)?.label ||
    item.action;
  const availableGroups =
    area === "history"
      ? []
      : [
          ...new Set(
            (snapshot?.catalog || [])
              .filter((item) => item.section === area)
              .map((item) => actionGroup(item.action)),
          ),
        ];
  const selectedGroup =
    area === "history"
      ? ""
      : availableGroups.includes(groups[area])
        ? groups[area]
        : availableGroups[0];
  const pending = operations.find((item) => pendingStates.includes(item.state));
  const showExecutionIndicator =
    active && (!pending || pending.state === "pending" || pending.state === "running");
  return (
    <section className="cluster-resources" aria-label="集群资源管理">
      {showExecutionIndicator && (
        <div className="resource-execution-indicator" role="status" aria-label="命令执行中">
          <BadouMascot animated size="large" />
          <strong>{pending ? labelFor(pending) : "正在提交命令"}</strong>
          <span>{pending?.state === "pending" ? "正在等待执行…" : "执行中，请稍候…"}</span>
        </div>
      )}
      <div className="resource-workspace-toolbar">
        <span>
          当前集群 <strong>{name}</strong>
        </span>
        <button type="button" disabled={loading} onClick={refresh}>
          {loading ? "正在刷新…" : "刷新已保存记录"}
        </button>
      </div>
      {!canManage && (
        <p className="resource-readonly">
          只读访问 ·
          可以浏览已保存资源与操作结果，执行远端操作需要集群管理权限。
        </p>
      )}
      {active && (
        <div className="resource-running" role="status">
          <span>
            {pending
              ? `${labelFor(pending)} · ${stateLabels[pending.state] || pending.state}`
              : "正在提交操作…"}
          </span>
          <button
            type="button"
            onClick={() => {
              setHistorySearch("");
              setHistoryState("");
              setArea("history");
            }}
          >
            查看进度
          </button>
        </div>
      )}
      {error && (!snapshot || area === "history") && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!snapshot && !error && <p>正在读取资源记录…</p>}
      {snapshot && (
        <>
          <ResourceNavigation
            area={area}
            snapshot={snapshot}
            operationCount={operations.length}
            onChange={setArea}
          />
          {sections.map((section) => (
            <div key={`${id}-${section.key}`} hidden={area !== section.key}>
              <ResourceSectionForm
                clusterId={id}
                section={section}
                snapshot={snapshot}
                disabled={!canManage || active}
                execute={execute}
                submissionError={area === section.key ? error : undefined}
                group={groups[section.key]}
                onGroupChange={(group) =>
                  setGroups((previous) =>
                    previous[section.key] === group
                      ? previous
                      : {
                          ...previous,
                          [section.key]: group,
                        },
                  )
                }
              />
            </div>
          ))}
          <ResourceHistory
            area={area}
            selectedGroup={selectedGroup}
            operations={operations}
            catalog={snapshot.catalog}
            canManage={canManage}
            userId={userId}
            onChange={accept}
            onOpenLog={(item, filename) => {
              const action = snapshot.catalog.find((entry) => entry.action === "mount.logs");
              const resourceId = item.payload?.resource_id;
              if (action && typeof resourceId === "string")
                void execute(action, { resource_id: resourceId, filename, lines: 500 });
            }}
            onShowHistory={() => setArea("history")}
            historySearch={historySearch}
            setHistorySearch={setHistorySearch}
            historyState={historyState}
            setHistoryState={setHistoryState}
          />
        </>
      )}
    </section>
  );
}
