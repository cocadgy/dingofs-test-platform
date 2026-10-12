import { useId, useMemo, useState } from "react";
import type { CacheCatalog, CacheOptions } from "./types";
import "./cache-profiles.css";

const COMMON_PARAMETERS = [
  "id", "cache_size_mb", "group_weight", "cache_dir", "log_dir", "log_level",
  "listen_ip", "listen_port", "mds_addrs", "cache_rdma_device",
  "cache_rdma_port_num", "cache_expire_s", "free_space_ratio",
];

export function CacheParameterEditor({
  catalog,
  values,
  onChange,
  disabled = false,
  creation = false,
  tool = "dingo-cache",
}: {
  catalog: CacheCatalog;
  values: CacheOptions;
  onChange: (values: CacheOptions) => void;
  disabled?: boolean;
  creation?: boolean;
  tool?: "dingo-cache" | "dingo-client";
}) {
  const id = useId();
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("");
  const [onlyChanged, setOnlyChanged] = useState(false);
  const groups = useMemo(
    () => [...new Set(catalog.fields.map((row) => row.group))],
    [catalog],
  );
  const orderedFields = useMemo(() => [...catalog.fields].sort((a, b) => {
    const left = COMMON_PARAMETERS.indexOf(a.name);
    const right = COMMON_PARAMETERS.indexOf(b.name);
    return (left < 0 ? COMMON_PARAMETERS.length : left) - (right < 0 ? COMMON_PARAMETERS.length : right);
  }), [catalog]);
  const rows = orderedFields.filter(
    (row) =>
      (!group || (group === "common" ? COMMON_PARAMETERS.includes(row.name) : row.group === group)) &&
      (!onlyChanged || Object.hasOwn(values, row.name)) &&
      `${row.name} ${row.label} ${row.description}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  function update(key: string, value: string | undefined) {
    const next = { ...values };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  }
  return (
    <section className="cache-parameter-editor" aria-label={tool === "dingo-client" ? "挂载启动参数" : "缓存启动参数"}>
      <p className="muted">
        参数来自 {tool} {catalog.source_version} · 共{" "}
        {catalog.fields.length}{" "}
        项。勾选“自定义”才会设置该参数；未设置时使用程序默认值。
      </p>
      {creation && (
        <p className="muted">
          容量、缓存目录和 RDMA
          参数在下方成员表单调整，以成员最终值为准。平台容量初始值为 1024
          MiB，与程序默认值不同。
        </p>
      )}
      <div className="cache-parameter-filters">
        <label>
          搜索参数
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="参数名、说明"
          />
        </label>
        <label>
          参数分类
          <select value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">全部分类</option>
            <option value="common">常用参数</option>
            {groups.map((g) => (
              <option key={g}>{g}</option>
            ))}
          </select>
        </label>
        <label className="cache-inline">
          <input
            type="checkbox"
            checked={onlyChanged}
            onChange={(e) => setOnlyChanged(e.target.checked)}
          />
          仅已配置（{Object.keys(values).length}）
        </label>
      </div>
      <div className="cache-parameter-scroll">
        <table className="cache-parameter-table">
          <thead>
            <tr>
              <th>参数 / 类型</th>
              <th>说明 / 默认值</th>
              <th>配置值</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const locked =
                row.managed ||
                (creation && row.member_key ? "在成员表单中设置" : "");
              const selected = Object.hasOwn(values, row.name);
              const inputId = `${id}-${row.name}`;
              return (
                <tr key={row.name}>
                  <td>
                    <strong>{row.label}</strong>
                    <code>--{row.name}</code>
                    <small>
                      {COMMON_PARAMETERS.includes(row.name) ? "常用参数 · " : ""}{row.group} · {row.type}
                    </small>
                  </td>
                  <td>
                    <p>{row.description}</p>
                    <small>
                      默认值：
                      <code>
                        {row.name === "id" ? "平台自动生成" : row.default === null
                          ? "帮助未声明"
                          : row.default === ""
                            ? "空字符串"
                            : row.default}
                      </code>
                    </small>
                    {row.note && <p className="muted">{row.note}</p>}
                  </td>
                  <td>
                    {locked ? (
                      <span className="muted">{locked}</span>
                    ) : (
                      <>
                        <label className="cache-inline">
                          <input
                            aria-label={`自定义 --${row.name}`}
                            type="checkbox"
                            checked={selected}
                            disabled={disabled}
                            onChange={(e) =>
                              update(
                                row.name,
                                e.target.checked
                                  ? (row.default ??
                                      (row.type === "bool" ? "false" : ""))
                                  : undefined,
                              )
                            }
                          />
                          自定义
                        </label>
                        {row.type === "bool" || row.choices ? (
                          <select
                            id={inputId}
                            aria-label={`参数 --${row.name}`}
                            disabled={disabled || !selected}
                            value={values[row.name] ?? row.default ?? ""}
                            onChange={(e) => update(row.name, e.target.value)}
                          >
                            {(row.choices || ["true", "false"]).map((v) => (
                              <option key={v}>{v}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            id={inputId}
                            aria-label={`参数 --${row.name}`}
                            disabled={disabled || !selected}
                            value={values[row.name] ?? ""}
                            placeholder={row.default ?? "未设置"}
                            inputMode={
                              row.type.includes("int")
                                ? "numeric"
                                : row.type === "double"
                                  ? "decimal"
                                  : undefined
                            }
                            required={selected && row.type !== "string"}
                            onChange={(e) => update(row.name, e.target.value)}
                          />
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <p className="muted">没有匹配的参数。</p>}
      </div>
    </section>
  );
}
