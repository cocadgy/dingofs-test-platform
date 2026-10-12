import { useState } from "react";
import { api } from "../../api/client";
import type { Parameters } from "../resources/types";
import { CacheParameterEditor } from "./CacheParameterEditor";
import {
  memberDefaults,
  type CacheCatalog,
  type CacheOptions,
  type CacheProfile,
} from "./types";

export function CacheProfileSelection({
  profiles,
  catalog,
  values,
  disabled,
  onChange,
  onRefresh,
}: {
  profiles: CacheProfile[];
  catalog: CacheCatalog;
  values: Parameters;
  disabled: boolean;
  onChange: (patch: Parameters) => void;
  onRefresh: (profiles: CacheProfile[], catalog: CacheCatalog) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = profiles.find((p) => p.id === values.cache_profile_id);
  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const [rows, data] = await Promise.all([
        api<CacheProfile[]>("/cache-profiles"),
        api<CacheCatalog>("/cache-profiles/catalog"),
      ]);
      onRefresh(rows, data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset
      className="resource-member cache-profile-selection"
      disabled={disabled || busy}
    >
      <legend>选择缓存组配置</legend>
      <div className="cache-profile-toolbar">
        <label>
          缓存组配置
          <select
            value={String(values.cache_profile_id || "")}
            onChange={(e) => {
              const p = profiles.find((row) => row.id === e.target.value);
              const options = { ...p?.parameters };
              const defaults = p
                ? {
                    cache_size_mb: 1024,
                    use_rdma: false,
                    rdma_device: "",
                    rdma_port: 1,
                    ...memberDefaults(options),
                  }
                : {};
              onChange({
                cache_profile_id: p?.id || "",
                cache_profile_revision: p?.revision || 0,
                cache_options: options,
                members: ((values.members as Parameters[]) || []).map((m) => ({
                  ...m,
                  ...defaults,
                })),
              });
            }}
          >
            <option value="">不使用模板 · 自定义本次参数</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.enabled}>
                {p.name}
                {p.enabled ? "" : "（已停用）"}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void refresh()}>
          {busy ? "刷新中…" : "刷新缓存组配置"}
        </button>
        <a href="#/cache-profiles" target="_blank" rel="noreferrer">
          管理缓存组配置 ↗
        </a>
      </div>
      <p className="muted">
        {selected?.description} 选择模板会应用成员容量和 RDMA
        默认值。以下修改仅用于本次创建，不会覆盖已保存的模板。
      </p>
      {!!values.cache_profile_id &&
        (!selected ||
          !selected.enabled ||
          selected.revision !== values.cache_profile_revision) && (
          <p role="alert" className="error">
            所选配置已更新、停用或删除，请重新选择配置。
          </p>
        )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <details>
        <summary>
          查看 / 修改本次启动参数（
          {
            Object.keys((values.cache_options as CacheOptions) || {}).length
          }{" "}
          项已配置）
        </summary>
        <CacheParameterEditor
          catalog={catalog}
          values={(values.cache_options as CacheOptions) || {}}
          creation
          disabled={disabled || busy}
          onChange={(cache_options) => onChange({ cache_options })}
        />
      </details>
    </fieldset>
  );
}
