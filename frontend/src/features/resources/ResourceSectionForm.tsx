import { mountLogUrl } from "./MountLogPage";
import {MountProfileSelection} from "../mount-profiles/MountProfileSelection";
import { CacheMemberInventory } from "./CacheMemberInventory";
import { CacheProfileSelection } from "../cache-profiles/CacheProfileSelection";
import {
  memberDefaults,
  type CacheOptions,
  type CacheProfile,
  type CacheCatalog,
} from "../cache-profiles/types";
import { CachePortPlan } from "./CachePortPlan";
import { cacheGroupResources } from "./cacheGroupResources";
import { StorageSelection } from "./StorageSelection";
import { shellMatches } from "./shellPattern";
import { useEffect, useMemo, useRef, useState } from "react";
import { filesystemOptions, selectsFilesystem } from "./filesystemOptions";
import { SavedResourcesTable } from "./SavedResourcesTable";
import { ResourceFields } from "./ResourceFields";
import {
  defaults,
  pendingStates,
  type ResourceOperation,
  type Parameters,
  type ResourceAction,
  type ResourceSnapshot,
  type SavedResource,
} from "./types";
import { actionGroup, sections } from "./workspace";
import type { Execute } from "./useResourceWorkspace";
import { useCacheMemberListing } from "./useCacheMemberListing";

function parameters(action: ResourceAction, values: Parameters) {
  return Object.fromEntries(
    action.fields
      .filter((field) => values[field.key] !== "" && values[field.key] != null)
      .map((field) => [
        field.key,
        field.type === "number" || field.key === "lines"
          ? Number(values[field.key])
          : values[field.key],
      ]),
  );
}

export function ResourceSectionForm({
  section,
  snapshot,
  disabled,
  execute,
  group,
  onGroupChange,
  submissionError,
  clusterId,
}: {
  clusterId?: string;
  section: (typeof sections)[number];
  snapshot: ResourceSnapshot;
  disabled: boolean;
  execute: Execute;
  group: string;
  submissionError?: string;
  onGroupChange: (group: string) => void;
}) {
  const [shortcutError, setShortcutError] = useState("");
  const actions = snapshot.catalog.filter(
    (action) =>
      action.section === section.key && action.action !== "cache.plan",
  );
  const groups = [...new Set(actions.map((item) => actionGroup(item.action)))];
  const selectedGroup = groups.includes(group) ? group : groups[0];
  const groupActions = actions.filter(
    (item) =>
      actionGroup(item.action) === selectedGroup &&
      item.action !== "cache.stop",
  );
  const formElement = useRef<HTMLFormElement>(null);
  const [addMemberRequest, setAddMemberRequest] = useState(0);
  const [form, setForm] = useState<{ action: string; values: Parameters }>({
    action: "",
    values: {},
  });
  const action =
    groupActions.find((item) => item.action === form.action) || groupActions[0];
  useEffect(() => {
    if (!addMemberRequest || action?.action !== "cache.create") return;
    formElement.current?.focus({preventScroll: true});
    formElement.current?.scrollIntoView?.({behavior: "smooth", block: "start"});
  }, [addMemberRequest, action?.action]);
  const values = action
    ? form.action === action.action
      ? form.values
      : defaults(action)
    : {};
  const [refreshedCache, setRefreshedCache] = useState<{
    profiles: CacheProfile[];
    catalog: CacheCatalog;
  }>();
  const cacheProfiles =
    refreshedCache?.profiles || snapshot.cache_profiles || [];
  const cacheCatalog =
    refreshedCache?.catalog || snapshot.cache_parameter_catalog;
  const chosenCacheProfile = cacheProfiles.find(
    (p) => p.id === values.cache_profile_id,
  );
  const cacheReady =
    action?.action !== "cache.create" ||
    !values.cache_profile_id ||
    Boolean(
      chosenCacheProfile?.enabled &&
      chosenCacheProfile.revision === values.cache_profile_revision,
    );
  const cacheMembers = useCacheMemberListing(snapshot, execute);
  const cacheInventory = useMemo(() => {
    if (
      !["cache", "mount"].includes(section.key) ||
      cacheMembers.pending ||
      cacheMembers.error ||
      cacheMembers.operation?.state !== "succeeded"
    )
      return { rows: [], error: "" };
    try {
      return {
        rows: cacheGroupResources(
          cacheMembers.operation,
          snapshot.resources,
          cacheMembers.options,
          [],
          snapshot.cache_member_targets,
        ),
        error: "",
      };
    } catch (error) {
      return { rows: [], error: (error as Error).message };
    }
  }, [
    section.key,
    cacheMembers.operation,
    cacheMembers.options,
    cacheMembers.pending,
    cacheMembers.error,
    snapshot.resources,
    snapshot.cache_member_targets,
  ]);
  const mountCacheGroupReady =
    action?.action !== "mount.create" ||
    !values.cache_group ||
    (!cacheMembers.pending &&
      !cacheMembers.error &&
      cacheMembers.operation?.state === "succeeded" &&
      !cacheInventory.error &&
      cacheInventory.rows.some((row) => row.name === values.cache_group));
  const planAction = snapshot.catalog.find(
    (item) => item.action === "cache.plan",
  );
  const portPlanning = action?.action === "cache.create" && Boolean(planAction);
  const [portPlan, setPortPlan] = useState<{
    operation: ResourceOperation;
    fingerprint: string;
  }>();
  const portFingerprint = JSON.stringify(values);
  const currentPlan =
    portPlan?.fingerprint === portFingerprint
      ? snapshot.operations.find((item) => item.id === portPlan.operation.id) ||
        portPlan.operation
      : undefined;
  const planReady = portPlanning && currentPlan?.state === "succeeded";
  const submittedPlans = useRef(new Set<string>());
  useEffect(() => {
    if (
      !planReady ||
      !currentPlan ||
      !action ||
      disabled ||
      submittedPlans.current.has(currentPlan.id)
    )
      return;
    submittedPlans.current.add(currentPlan.id);
    void execute(
      action,
      { plan_id: currentPlan.id },
      () => setPortPlan(undefined),
      undefined,
      { autoCreateFromPlan: true },
    );
  }, [planReady, currentPlan, action, disabled, execute]);

  const cacheBatch = action?.action === "cache.delete_batch";
  const deletingCacheMember =
    cacheBatch ||
    (action?.action === "cache.delete" &&
      action.fields.some((field) => field.key === "member_id"));

  const [listing, setListing] = useState<{
    loading: boolean;
    operation?: ResourceOperation;
    error?: string;
  }>({ loading: false });
  const [pattern, setPattern] = useState("");
  const [excluded, setExcluded] = useState<string[]>([]);
  const batch = action?.action === "fs.delete_batch";
  const cacheMatches =
    cacheBatch && pattern.trim()
      ? cacheMembers.options.filter(
          (member) =>
            shellMatches(pattern, member.groupName) ||
            shellMatches(pattern, member.id),
        )
      : [];
  const selectedMembers = cacheMatches
    .filter((member) => member.selectable && !excluded.includes(member.id))
    .map((member) => member.id);
  const cacheSelectionReady =
    !cacheMembers.pending &&
    !cacheMembers.error &&
    (cacheBatch
      ? selectedMembers.length > 0 && selectedMembers.length <= 100
      : cacheMembers.options.some(
          (member) => member.id === values.member_id && member.selectable,
        ));
  const listSequence = useRef(0);
  useEffect(
    () => () => {
      listSequence.current++;
    },
    [],
  );
  const creatingFilesystem = action?.action === "fs.create";
  const storageProfiles = snapshot.storage_profiles || [];
  const selectedStorage = storageProfiles.find(
    (profile) => profile.id === values.storage_profile_id,
  );
  const storageReady =
    !creatingFilesystem ||
    Boolean(
      selectedStorage?.enabled &&
      selectedStorage.has_secrets &&
      selectedStorage.revision === values.storage_profile_revision,
    );
  const usesFilesystemId = Boolean(
    action &&
    selectsFilesystem(action.action) &&
    action.fields.some((field) => field.key === "fs_id"),
  );
  const displayAction =
    ["cache.create", "mount.create"].includes(action?.action || "") && action
      ? {
          ...action,
          fields: action.fields.filter(
            (f) =>
              ![
                "cache_profile_id",
                "cache_profile_revision",
                "cache_options",
                "mount_profile_id", "mount_profile_revision", "mount_options",
              ].includes(f.key),
          ),
        }
      : creatingFilesystem && action
        ? {
            ...action,
            fields: action.fields.filter((field) =>
              ["fs_name", "partition_type"].includes(field.key),
            ),
          }
        : usesFilesystemId && action
          ? {
              ...action,
              fields: action.fields.map((field) =>
                field.key === "fs_id"
                  ? {
                      ...field,
                      key: "fs_name",
                      label: "文件系统名称",
                      type: "text" as const,
                    }
                  : field,
              ),
            }
          : action;
  const needsFilesystem = Boolean(action && selectsFilesystem(action.action));
  const listOperation =
    snapshot.operations.find((item) => item.id === listing.operation?.id) ||
    listing.operation;
  useEffect(() => {
    if (listOperation)
      setListing((previous) =>
        previous.operation === listOperation
          ? previous
          : { ...previous, operation: listOperation },
      );
  }, [listOperation]);
  const listPending =
    listing.loading ||
    Boolean(listOperation && pendingStates.includes(listOperation.state));
  const { options, names, listError } = useMemo(() => {
    let options = [] as ReturnType<typeof filesystemOptions>;
    let listError = listing.error || "";
    if (listOperation && !listPending) {
      if (listOperation.state === "succeeded") {
        try {
          options = filesystemOptions(listOperation);
        } catch (error) {
          listError = (error as Error).message;
        }
      } else
        listError =
          listOperation.message || "文件系统列表获取失败，请查看下方操作记录。";
    }
    return { options, names: options.map((option) => option.name), listError };
  }, [listOperation, listPending, listing.error]);
  const selectedFilesystem = options.find(
    (option) => option.name === values.fs_name,
  );
  const validFilesystemId =
    !usesFilesystemId ||
    (selectedFilesystem?.id !== undefined &&
      selectedFilesystem.id === values.fs_id);
  const matches =
    batch && pattern.trim()
      ? names.filter((name) => shellMatches(pattern, name))
      : [];
  const selected = matches.filter((name) => !excluded.includes(name));
  const selectionReady =
    !listPending &&
    !listError &&
    (batch
      ? selected.length > 0 && selected.length <= 100
      : names.includes(String(values.fs_name || "")) && validFilesystemId);
  async function refreshFilesystems() {
    const sequence = ++listSequence.current;
    const listAction = snapshot.catalog.find(
      (item) => item.action === "fs.list",
    );
    setExcluded([]);
    setListing({ loading: true });
    let accepted: ResourceOperation | undefined;
    try {
      if (!listAction) throw new Error("当前集群不支持查询文件系统列表。");
      await execute(listAction, {}, undefined, (next) => {
        accepted = next;
      });
      if (sequence === listSequence.current)
        setListing(
          accepted
            ? { loading: false, operation: accepted }
            : { loading: false, error: "未能获取文件系统列表，请刷新重试。" },
        );
    } catch (error) {
      if (sequence === listSequence.current)
        setListing({ loading: false, error: (error as Error).message });
    }
  }
  const moduleLists = action?.action === "mount.create" ||
    section.key === "filesystem" &&
    ["基础操作", "文件系统配额", "目录配额", "回收站", "目录统计"].includes(
      selectedGroup,
    );
  const entered = useRef(false);
  const refreshRef = useRef(refreshFilesystems);
  refreshRef.current = refreshFilesystems;
  const supportsList = snapshot.catalog.some(
    (item) => item.action === "fs.list",
  );
  useEffect(() => {
    // This form stays mounted while tabs/modules change. Reset only when
    // the resource page unmounts (including switching to another cluster).
    if (
      section.key !== "filesystem" ||
      disabled ||
      !supportsList ||
      entered.current
    )
      return;
    let cancelled = false;
    // Defer the entry request so StrictMode's replay does not submit twice.
    queueMicrotask(() => {
      if (cancelled || entered.current) return;
      entered.current = true;
      void refreshRef.current();
    });
    return () => {
      cancelled = true;
    };
  }, [section.key, disabled, supportsList]);
  function setValues(update: (previous: Parameters) => Parameters) {
    if (action) setForm({ action: action.action, values: update(values) });
  }
  function choose(next: ResourceAction, preset: Parameters = {}) {
    setPattern("");
    setExcluded([]);
    if (actionGroup(next.action) !== selectedGroup)
      onGroupChange(actionGroup(next.action));
    setForm({ action: next.action, values: { ...defaults(next), ...preset } });
  }
  function deleteUngroupedMembers() {
    if (disabled || cacheMembers.pending || cacheMembers.error) return;
    const all = cacheMembers.options.filter(member => !member.groupName);
    const eligible = all.filter(member => member.selectable);
    const next = actions.find(item => item.action === "cache.delete_batch");
    if (!next || !eligible.length) return;
    const batch = eligible.slice(0, 100);
    void execute({...next, label: `删除未分组成员 ${batch.length} 个，跳过 ${all.length - eligible.length} 个在线或状态不允许删除的成员；保留缓存数据${eligible.length > 100 ? `；剩余 ${eligible.length - 100} 个请在本批完成后继续删除` : ""}`},
      {member_ids: batch.map(member => member.id)});
  }
  function shortcut(resource: SavedResource, key: string, memberId?: string) {
    if (disabled) return;
    const force = key === "cache.force_stop";
    if (force) key = "cache.stop";
    setShortcutError("");
    if (["cache.leave", "cache.unlock", "cache.weight"].includes(key) && memberId) {
      const member = cacheMembers.options.find(item => item.id === memberId);
      const next = actions.find(item => item.action === key);
      if (!member || !next || cacheMembers.pending || cacheMembers.error) return;
      const params: Parameters = {member_id: member.id, group_name: member.groupName};
      if (key === "cache.weight") {
        const input = window.prompt("设置成员权重（0～4294967295）", "100");
        if (input === null) return;
        if (!/^\d+$/.test(input.trim()) || Number(input) > 4294967295) {
          setShortcutError("权重必须是 0～4294967295 的整数");
          return;
        }
        params.weight = Number(input);
      }
      void execute({...next, label: `${next.label}：${member.id} (${member.address})，${member.groupName || "未分组"}${key === "cache.leave" ? "；仅离组，保留成员及运行进程" : ""}`}, params);
      return;
    }
    if (key === "cache.create") {
      const next = actions.find((item) => item.action === key);
      if (next) {
        choose(next, { group_name: resource.name });
        setAddMemberRequest(value => value + 1);
      }
      return;
    }
    if (
      key === "cache.stop" &&
      resource.data.queried_inventory &&
      Array.isArray(resource.data.members)
    ) {
      if (
        cacheMembers.pending ||
        cacheMembers.error ||
        !cacheMembers.operation
      ) {
        setShortcutError("请先成功刷新缓存成员列表，再停止成员。");
        return;
      }
      const members = resource.data.members.filter(
        (member) => !memberId || member.member_id === memberId,
      );
      if (!members.length) {
        setShortcutError("没有匹配的成员，请刷新列表。");
        return;
      }
      const activeMembers = members.filter((member) => member.state !== "离线");
      if (!activeMembers.length) {
        setShortcutError("所选成员均已离线，无需再次停止。");
        return;
      }
      if (activeMembers.some((member) => !member.can_stop)) {
        setShortcutError(
          activeMembers.find((member) => !member.can_stop)?.stop_reason ||
            "部分成员无法定位执行机器，请展开成员列表核实。",
        );
        return;
      }
      if (activeMembers.length > 100) {
        setShortcutError("单次最多停止 100 个成员，请分批操作。");
        return;
      }
      const next = actions.find((item) => item.action === "cache.stop");
      if (next)
        void execute(
          {
            ...next,
            label: `${force ? "强制停止（kill -9，不执行进程退出清理）" : "平滑停止（kill，SIGTERM）"}${memberId ? "成员" : "缓存组全部成员"}「${resource.name}」：${activeMembers.map((m) => `${m.member_id} (${m.address})`).join("、")}；${members.length - activeMembers.length} 个离线成员跳过`,
          },
          { member_ids: activeMembers.map((member) => member.member_id), ...(force ? {force:true} : {}) },
        );
      return;
    }
    if (key === "cache.delete") {
      if (
        cacheMembers.pending ||
        cacheMembers.error ||
        !cacheMembers.operation
      ) {
        setShortcutError("请先成功刷新缓存成员列表，再删除缓存组成员登记。");
        return;
      }
      const members = cacheMembers.options.filter(
        (member) =>
          member.groupName === resource.name &&
          (!memberId || member.id === memberId),
      );
      if (!members.length) {
        setShortcutError(
          "该组当前没有可删除的成员登记，请刷新缓存成员列表确认。",
        );
        return;
      }
      if (members.some((member) => !member.selectable)) {
        setShortcutError(
          "该组包含在线或状态不允许删除的成员，请先停止对应缓存进程，等待离线后刷新列表。",
        );
        return;
      }
      if (members.length > 100) {
        setShortcutError("该组超过 100 个成员，请使用通配符批量删除分批选择。");
        return;
      }
      const next = actions.find(
        (item) =>
          item.action ===
          (members.length === 1 ? "cache.delete" : "cache.delete_batch"),
      );
      if (!next) {
        setShortcutError("当前服务未提供对应删除操作，请更新服务后刷新页面。");
        return;
      }
      void execute(
        {
          ...next,
          label: `删除${resource.name ? `缓存组「${resource.name}」的` : "未分组的"} ${members.length} 个成员登记（保留缓存数据）：${members.map((m) => `${m.id} (${m.address})`).join("、")}`,
        },
        members.length === 1
          ? { member_id: members[0].id }
          : { member_ids: members.map((member) => member.id) },
      );
      return;
    }
    const next = actions.find((item) => item.action === key);
    if (!next) return;
    if (key === "mount.logs" && clusterId) {
      window.location.hash = mountLogUrl(clusterId, resource.id);
      return;
    }
    choose(next, { resource_id: resource.id });
    if (key !== "mount.logs") void execute(next, { resource_id: resource.id });
  }
  const resources = snapshot.resources.filter(
    (resource) => resource.kind === section.key,
  );
  return (
    <section className="resource-section" aria-label={section.label}>
      <h3>{section.label}</h3>
      {shortcutError && (
        <p role="alert" className="error">
          {shortcutError}
        </p>
      )}
      <p className="muted">{section.hint}</p>
      {section.key === "cache" && (
        <div>
          {cacheMembers.pending && !deletingCacheMember && (
            <p role="status">正在查询缓存组与成员列表…</p>
          )}
          {(cacheInventory.error ||
            (cacheMembers.error && !deletingCacheMember)) && (
            <p role="alert" className="error">
              {cacheInventory.error || cacheMembers.error}
            </p>
          )}
          {!cacheMembers.operation && (
            <p className="muted">
              尚未获取实际缓存组列表，请执行「缓存组与成员列表」查询。
            </p>
          )}
          {cacheMembers.operation?.state === "succeeded" &&
            !cacheMembers.pending &&
            !cacheMembers.error &&
            !cacheInventory.error && (
              <>
              <SavedResourcesTable
                queried
                resources={cacheInventory.rows}
                machines={snapshot.machines}
                actions={actions}
                disabled={disabled}
                onAction={shortcut}
                onMemberAction={shortcut}
              />
              <CacheMemberInventory members={cacheMembers.options} resources={snapshot.resources}
                onManage={(member, key) => shortcut({id:`member:${member.id}`, name:member.groupName, kind:"cache", state:"unknown", created_at:"", data:{}}, key, member.id)}
                actions={actions}
                onDeleteUngrouped={actions.some(item => item.action === "cache.delete_batch") ? deleteUngroupedMembers : undefined}
                disabled={disabled || !actions.some(item => item.action === "cache.delete")}
                onDelete={member => shortcut({id: `member:${member.id}`, name: member.groupName,
                  kind: "cache", state: "unknown", created_at: "", data: {}}, "cache.delete", member.id)} />
              </>
            )}
          {!cacheMembers.operation &&
            resources.some((item) =>
              ["running", "stopped", "partial"].includes(item.state),
            ) && (
              <div aria-label="平台托管记录">
                <p className="muted">
                  以下仅为平台托管记录，不代表当前 MDS 缓存组列表。
                </p>
                <SavedResourcesTable
                  resources={resources.filter((item) =>
                    ["running", "stopped", "partial"].includes(item.state),
                  )}
                  machines={snapshot.machines}
                  actions={actions}
                  disabled={disabled}
                  onAction={shortcut}
                  onMemberAction={shortcut}
                />
              </div>
            )}
        </div>
      )}
      {section.key === "mount" && (
        <SavedResourcesTable
          resources={resources}
          machines={snapshot.machines}
          actions={actions}
          disabled={disabled}
          onAction={shortcut}
          onMemberAction={shortcut}
        />
      )}
      <div
        className={
          groups.length > 1
            ? "resource-task-layout"
            : "resource-task-layout single"
        }
      >
        {groups.length > 1 && (
          <nav className="resource-subnav" aria-label={`${section.label}功能`}>
            {groups.map((item) => (
              <button
                key={item}
                type="button"
                aria-current={selectedGroup === item ? "page" : undefined}
                onClick={() => {
                  if (item === selectedGroup) return;
                  const next = actions.find(
                    (action) => actionGroup(action.action) === item,
                  );
                  if (next) choose(next);
                }}
              >
                {item}
              </button>
            ))}
          </nav>
        )}
        <div className="resource-task-content">
          {action ? (
            <form ref={formElement} tabIndex={-1} aria-label="资源操作表单"
              onSubmit={(event) => {
                event.preventDefault();
                if (
                  disabled ||
                  !storageReady ||
                  !cacheReady ||
                  !mountCacheGroupReady ||
                  (needsFilesystem && !selectionReady) ||
                  (deletingCacheMember && !cacheSelectionReady)
                )
                  return;
                if (action.action === "mount.logs" && clusterId && typeof values.resource_id === "string") {
                  window.location.hash = mountLogUrl(clusterId, values.resource_id);
                  return;
                }
                if (action.action === "fs.list") return;
                if (action.action === "cache.list") {
                  void cacheMembers.refresh();
                  return;
                }
                if (portPlanning && planAction) {
                  void execute(
                    planAction,
                    parameters(action, values),
                    undefined,
                    (operation) =>
                      setPortPlan({ operation, fingerprint: portFingerprint }),
                  );
                  return;
                }
                void execute(
                  action,
                  batch
                    ? { fs_names: [...selected] }
                    : cacheBatch
                      ? { member_ids: [...selectedMembers] }
                      : creatingFilesystem
                        ? {
                            fs_name: values.fs_name,
                            partition_type: values.partition_type || "hash",
                            storage_profile_id: values.storage_profile_id,
                            storage_profile_revision:
                              values.storage_profile_revision,
                          }
                        : parameters(action, values),
                  () =>
                    setValues((previous) => ({
                      ...previous,
                      ...Object.fromEntries(
                        action.fields
                          .filter((field) => field.type === "password")
                          .map((field) => [field.key, ""]),
                      ),
                    })),
                );
              }}
            >
              {addMemberRequest > 0 && action.action === "cache.create" && (
                <p role="status">正在向缓存组「{String(values.group_name || "")}」添加成员，请填写成员机器及参数后提交。</p>
              )}
              <div className="resource-task-heading">
                <div>
                  <small>当前功能</small>
                  <h4>{selectedGroup}</h4>
                </div>
                <span className="resource-mode">
                  {action.mutating ? "变更操作" : "只读查询"}
                </span>
              </div>
              <div
                className="resource-action-buttons"
                role="group"
                aria-label={selectedGroup}
              >
                {groupActions.map((item) => (
                  <button
                    key={item.action}
                    type="button"
                    disabled={disabled}
                    aria-pressed={action.action === item.action}
                    onClick={() => {
                      if (item.action !== action.action) choose(item);
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              {deletingCacheMember && (
                <div>
                  <p className="muted">
                    仅删除离线或状态未知成员的登记；不会停止成员进程。
                  </p>
                  {cacheMembers.pending && (
                    <p role="status">
                      正在获取缓存成员列表；如需认证，请在下方操作记录中完成。
                    </p>
                  )}
                  {cacheMembers.error && (
                    <p role="alert" className="error">
                      {cacheMembers.error}
                    </p>
                  )}
                  {!cacheMembers.pending &&
                    !cacheMembers.error &&
                    !cacheMembers.options.length && (
                      <p className="muted">
                        {cacheMembers.operation
                          ? "当前查询未返回缓存成员。"
                          : "请先刷新缓存成员列表，再选择要删除的成员登记。"}
                      </p>
                    )}
                  <button
                    type="button"
                    disabled={disabled || cacheMembers.pending}
                    onClick={() => {
                      setValues((previous) => ({ ...previous, member_id: "" }));
                      void cacheMembers.refresh();
                    }}
                  >
                    刷新缓存成员列表
                  </button>
                </div>
              )}
              {action.action === "mount.create" && <div>
                <button type="button" disabled={disabled || cacheMembers.pending} onClick={() => void cacheMembers.refresh()}>刷新缓存组列表</button>
                {cacheMembers.pending && <p role="status">正在获取缓存组列表…</p>}
                {(cacheMembers.error || cacheInventory.error) && <p role="alert">{cacheMembers.error || cacheInventory.error}</p>}
                {!cacheMembers.operation && <p>尚未查询缓存组，请点击刷新缓存组列表。</p>}
              </div>}
              {moduleLists && (
                <div>
                  {listPending && (
                    <p role="status">
                      正在获取文件系统列表；如需认证，请在下方操作记录中完成。
                    </p>
                  )}
                  {listError && (
                    <p role="alert" className="error">
                      {listError}
                    </p>
                  )}
                  {!listPending &&
                    !listError &&
                    listOperation?.state === "succeeded" &&
                    !names.length && <p>暂无文件系统</p>}
                  <button
                    type="button"
                    disabled={disabled || listPending}
                    onClick={() => {
                      setValues((previous) => ({
                        ...previous,
                        fs_name: "",
                        fs_id: "",
                      }));
                      void refreshFilesystems();
                    }}
                  >
                    刷新文件系统列表
                  </button>
                </div>
              )}
              {batch ? (
                <div>
                  <label>
                    文件系统名通配符
                    <input
                      value={pattern}
                      maxLength={256}
                      disabled={disabled || listPending}
                      placeholder="例如 vdbench*"
                      onChange={(event) => {
                        setPattern(event.target.value);
                        setExcluded([]);
                      }}
                    />
                  </label>
                  <p>
                    Shell 通配符完整匹配名称；匹配 {matches.length} 个，已选择{" "}
                    {selected.length} 个（每批最多 100 个）。
                  </p>

                  <p className="muted">
                    * 匹配任意长度字符，? 匹配一个字符，[abc]
                    匹配其中一个字符，[0-9] 匹配数字，[!abc]
                    排除指定字符。例：vdbench*。不支持花括号展开或扩展通配符。
                  </p>
                  {matches.map((name) => (
                    <label key={name} style={{ display: "block" }}>
                      <input
                        type="checkbox"
                        disabled={disabled || listPending}
                        checked={!excluded.includes(name)}
                        onChange={(event) =>
                          setExcluded((previous) =>
                            event.target.checked
                              ? previous.filter((item) => item !== name)
                              : [...previous, name],
                          )
                        }
                      />
                      {name}
                    </label>
                  ))}
                  <p className="muted">
                    确认后仅删除选定名单中的文件系统，新增匹配项不会自动加入。连接中断或超时后未执行项需重新查询确认。
                  </p>
                </div>
              ) : cacheBatch ? (
                <div>
                  <label>
                    缓存组名或成员 ID 通配符
                    <input
                      value={pattern}
                      maxLength={256}
                      disabled={disabled || cacheMembers.pending}
                      placeholder="例如 vdbench_cache_group*"
                      onChange={(event) => {
                        setPattern(event.target.value);
                        setExcluded([]);
                      }}
                    />
                  </label>
                  <p>
                    Shell 通配符完整匹配缓存组名或成员 ID；匹配{" "}
                    {cacheMatches.length} 个，已选择 {selectedMembers.length}{" "}
                    个（每批最多 100 个）。
                  </p>
                  <p className="muted">
                    * 匹配任意长度字符，?
                    匹配一个字符；在线成员不可选择。只删除成员登记，保留缓存数据目录。
                  </p>
                  {cacheMatches.map((member) => (
                    <label key={member.id} style={{ display: "block" }}>
                      <input
                        type="checkbox"
                        disabled={
                          disabled || cacheMembers.pending || !member.selectable
                        }
                        checked={
                          member.selectable && !excluded.includes(member.id)
                        }
                        onChange={(event) =>
                          setExcluded((previous) =>
                            event.target.checked
                              ? previous.filter((id) => id !== member.id)
                              : [...previous, member.id],
                          )
                        }
                      />
                      {member.groupName} · {member.id} · {member.address} ·{" "}
                      {member.stateLabel}
                    </label>
                  ))}
                  <p className="muted">
                    确认后仅删除选定名单中的成员；连接中断或超时后，请重新查询并核实未返回结果的成员。
                  </p>
                </div>
              ) : (
                <>
                  {action.action === "cache.create" && cacheCatalog && (
                    <CacheProfileSelection
                      profiles={cacheProfiles}
                      catalog={cacheCatalog}
                      values={values}
                      disabled={disabled}
                      onChange={(patch) =>
                        setValues((previous) => ({ ...previous, ...patch }))
                      }
                      onRefresh={(profiles, catalog) =>
                        setRefreshedCache({ profiles, catalog })
                      }
                    />
                  )}
                  {action.action === "mount.create" && snapshot.mount_parameter_catalog && <MountProfileSelection
                    profiles={snapshot.mount_profiles || []} catalog={snapshot.mount_parameter_catalog} values={values} disabled={disabled}
                    onChange={patch=>setValues(previous=>({...previous,...patch}))} />}
                  <ResourceFields
                    action={displayAction!}
                    values={values}
                    filesystemOptions={needsFilesystem ? names : undefined}
                    cacheGroupOptions={cacheInventory.rows.map(row => row.name)}
                    cacheMemberOptions={cacheMembers.options}
                    portPlanning={portPlanning}
                    cacheMemberDefaults={memberDefaults(
                      (values.cache_options as CacheOptions) || {},
                    )}
                    machines={snapshot.machines}
                    resources={snapshot.resources}
                    disabled={
                      disabled ||
                      Boolean(deletingCacheMember && cacheMembers.pending)
                    }
                    onChange={(key, value) =>
                      setValues((previous) => ({
                        ...previous,
                        [key]: value,
                        ...(usesFilesystemId && key === "fs_name"
                          ? {
                              fs_id:
                                options.find((option) => option.name === value)
                                  ?.id ?? "",
                            }
                          : {}),
                      }))
                    }
                  />
                </>
              )}
              {usesFilesystemId &&
                selectedFilesystem &&
                selectedFilesystem.id === undefined && (
                  <p role="alert" className="error">
                    所选记录未返回有效的文件系统 ID，请刷新列表后重试。
                  </p>
                )}
              {creatingFilesystem && (
                <StorageSelection
                  profiles={storageProfiles}
                  id={String(values.storage_profile_id || "")}
                  revision={Number(values.storage_profile_revision || 0)}
                  disabled={
                    disabled ||
                    Boolean(deletingCacheMember && cacheMembers.pending)
                  }
                  onChange={(profile) =>
                    setValues((previous) => ({
                      ...previous,
                      storage_profile_id: profile?.id || "",
                      storage_profile_revision: profile?.revision || 0,
                    }))
                  }
                />
              )}
              {action.action === "mount.logs" && (
                <p className="muted">
                  文件名留空时列出可用日志；选择文件后读取末尾 100 / 500 / 1000
                  行，再次执行可刷新。仅填写文件名，不包含目录。
                </p>
              )}
              {planReady && currentPlan && (
                <CachePortPlan
                  operation={currentPlan}
                  machines={snapshot.machines}
                />
              )}
              {portPlanning &&
                currentPlan &&
                currentPlan.state !== "succeeded" && (
                  <p role="status">
                    {pendingStates.includes(currentPlan.state)
                      ? "正在检查端口；如需认证，请在下方操作记录中完成。"
                      : currentPlan.message ||
                        "端口检查未通过，请查看下方结果并修改后重试。"}
                  </p>
                )}
              {action.action !== "fs.list" && (
                <div className="resource-submit-row">
                  <button
                    className="primary"
                    disabled={
                      disabled ||
                      !storageReady ||
                      !cacheReady ||
                  !mountCacheGroupReady ||
                      (needsFilesystem && !selectionReady) ||
                      (deletingCacheMember && !cacheSelectionReady)
                    }
                  >
                    {portPlanning ? "检查并创建缓存组" : `执行${action.label}`}
                  </button>
                  <small>
                    {portPlanning
                      ? "端口检查通过后自动创建，无需再次确认。"
                      : action.mutating
                        ? "提交后确认操作目标与参数。"
                        : "执行后在下方查看本次查询结果。"}
                  </small>
                </div>
              )}
              {submissionError && (
                <p role="alert" className="error">
                  {submissionError}
                </p>
              )}
            </form>
          ) : (
            <p>没有可用操作。</p>
          )}
        </div>
      </div>
    </section>
  );
}
