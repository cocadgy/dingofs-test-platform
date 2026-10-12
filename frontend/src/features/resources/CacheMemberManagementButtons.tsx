import type { ResourceAction } from "./types";
export function CacheMemberManagementButtons({memberId, grouped, actions, disabled, onAction}: {
  memberId: string; grouped: boolean; actions: ResourceAction[]; disabled: boolean; onAction: (key: string) => void;
}) {
  return <>{[["cache.leave", "离开缓存组"], ["cache.unlock", "解锁"], ["cache.weight", "设置权重"]]
    .filter(([key]) => actions.some(action => action.action === key) && (key !== "cache.leave" || grouped))
    .map(([key, label]) => <button type="button" key={key} disabled={disabled}
      aria-label={`${label}成员 ${memberId}`} onClick={() => onAction(key)}>{label}</button>)}</>;
}
