import type { StorageProfile } from "../storage/types";

export function StorageSelection({
  profiles,
  id,
  revision,
  disabled,
  onChange,
}: {
  profiles: StorageProfile[];
  id: string;
  revision: number;
  disabled: boolean;
  onChange: (profile: StorageProfile | undefined) => void;
}) {
  const available = profiles.filter((profile) => profile.enabled);
  const selected = available.find((profile) => profile.id === id);
  const stale = Boolean(id && (!selected || selected.revision !== revision));
  const fields =
    selected?.storage_type === "s3"
      ? [
          ["s3_endpoint", "Endpoint"],
          ["s3_bucketname", "Bucket"],
        ]
      : [
          ["rados_mon", "Monitor 地址"],
          ["rados_poolname", "Pool"],
          ["rados_username", "RADOS 用户"],
          ["rados_clustername", "集群名称"],
        ];
  return (
    <fieldset
      disabled={disabled}
      className="resource-member resource-storage-selection"
    >
      <legend>存储连接</legend>
      <label>
        存储配置
        <select
          required
          value={stale ? "" : id}
          onChange={(event) =>
            onChange(
              available.find((profile) => profile.id === event.target.value),
            )
          }
        >
          <option value="">请选择存储配置</option>
          {available.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name} · {profile.storage_type.toUpperCase()}
            </option>
          ))}
        </select>
      </label>
      {!available.length && (
        <p>尚无可用存储配置，请先登记或启用存储配置，再刷新本页记录。</p>
      )}
      {stale && (
        <p role="alert" className="error">
          所选配置已变更或停用，请重新选择并核对连接信息。
        </p>
      )}
      {selected && (
        <dl className="resource-storage-summary">
          {fields.map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{selected.parameters[key] || "—"}</dd>
            </div>
          ))}
          <div>
            <dt>访问凭据</dt>
            <dd>
              {selected.has_secrets ? "已配置，创建时自动使用" : "未配置"}
            </dd>
          </div>
        </dl>
      )}
      <a href="#/storage">管理存储配置</a>
    </fieldset>
  );
}
