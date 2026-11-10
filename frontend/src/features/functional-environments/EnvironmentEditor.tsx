import { useState } from "react";
export type Choice = {
  id: string;
  name: string;
  can_manage?: boolean;
  address?: string;
};
type ClientDraft = {
  dingo_tool_path?: string;
  machine_id: string;
  client_count: number;
  mount_path: string;
  fs_name: string;
  client_conf: Record<string, string | number | boolean>;
};
type CacheDraft = {
  dingo_tool_path?: string;
  machine_id: string;
  remote_cache_count: number;
  remote_cache_conf: Record<string, string | number | boolean>;
};
export type Draft = {
  id?: string;
  sourceId?: string;
  revision?: number;
  name: string;
  cluster_id: string;
  machine_id: string;
  storage_profile_id: string;
  mount_root: string;
  fs_prefix: string;
  binaries: Record<string, string>;
  clients: ClientDraft[];
  remote_caches: CacheDraft[];
  enabled: boolean;
};
function FlagEditor({
  value,
  onChange,
}: {
  value: Record<string, string | number | boolean>;
  onChange: (value: Record<string, string | number | boolean>) => void;
}) {
  const [name, setName] = useState("");
  const [flagValue, setFlagValue] = useState("");
  return (
    <details>
      <summary>高级参数 · {Object.keys(value).length} 项</summary>
      <div className="functional-environments-flags">
        {Object.entries(value).map(([key, current]) => (
          <div key={key}>
            <code>{key}</code>
            <input
              aria-label={`${key} 的值`}
              value={String(current)}
              onChange={(e) => onChange({ ...value, [key]: e.target.value })}
            />
            <button
              type="button"
              onClick={() => {
                const next = { ...value };
                delete next[key];
                onChange(next);
              }}
            >
              删除
            </button>
          </div>
        ))}
        <div>
          <input
            aria-label="参数名"
            placeholder="--flag_name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            aria-label="参数值"
            value={flagValue}
            onChange={(e) => setFlagValue(e.target.value)}
          />
          <button
            type="button"
            disabled={!/^--[a-zA-Z][a-zA-Z0-9_]*$/.test(name)}
            onClick={() => {
              onChange({ ...value, [name]: flagValue });
              setName("");
              setFlagValue("");
            }}
          >
            添加参数
          </button>
        </div>
      </div>
    </details>
  );
}

export function EnvironmentEditor({
  draft,
  change,
  close,
  save,
  busy,
  clusters,
  machines,
  storage,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
  close: () => void;
  save: () => Promise<void>;
  busy: boolean;
  clusters: Choice[];
  machines: Choice[];
  storage: (Choice & { enabled: boolean })[];
}) {
  return (
    <fieldset disabled={busy} className="functional-environments-editor">
      <h2>
        {draft.id
          ? "编辑测试环境"
          : draft.sourceId
            ? "复制预置环境"
            : "新建测试环境"}
      </h2>
      <div className="functional-environments-fields">
        <label>
          名称
          <input
            value={draft.name}
            onChange={(e) => change({ name: e.target.value })}
          />
        </label>
        <label>
          测试集群
          <select
            value={draft.cluster_id}
            onChange={(e) => change({ cluster_id: e.target.value })}
          >
            <option value="">选择集群</option>
            {clusters.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          测试机
          <select
            value={draft.machine_id}
            onChange={(e) => change({ machine_id: e.target.value })}
          >
            <option value="">选择机器</option>
            {machines
              .filter((x) => x.can_manage)
              .map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name} · {x.address}
                </option>
              ))}
          </select>
        </label>
        <label>
          存储配置
          <select
            value={draft.storage_profile_id}
            onChange={(e) => change({ storage_profile_id: e.target.value })}
          >
            <option value="">选择存储</option>
            {storage
              .filter((x) => x.enabled && x.can_manage)
              .map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          挂载根目录
          <input
            value={draft.mount_root}
            onChange={(e) => change({ mount_root: e.target.value })}
          />
        </label>
        <label>
          文件系统名前缀
          <input
            value={draft.fs_prefix}
            onChange={(e) => change({ fs_prefix: e.target.value })}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => change({ enabled: e.target.checked })}
          />
          启用
        </label>
      </div>
      <section>
        <h3>客户端挂载配置</h3>
        <p>
          每项的目录和前缀优先于基本信息。留空时使用上方测试机创建一个客户端。
        </p>
        {draft.clients.map((item, index) => (
          <div className="functional-environments-member" key={index}>
            <div className="functional-environments-fields">
              <label>
                客户端机器
                <select
                  value={item.machine_id}
                  onChange={(e) =>
                    change({
                      clients: draft.clients.map((x, i) =>
                        i === index ? { ...x, machine_id: e.target.value } : x,
                      ),
                    })
                  }
                >
                  <option value="">选择机器</option>
                  {machines
                    .filter((x) => x.can_manage)
                    .map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.name} · {x.address}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                实例数
                <input
                  type="number"
                  min="1"
                  value={item.client_count}
                  onChange={(e) =>
                    change({
                      clients: draft.clients.map((x, i) =>
                        i === index
                          ? { ...x, client_count: Number(e.target.value) }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                挂载根目录
                <input
                  value={item.mount_path}
                  onChange={(e) =>
                    change({
                      clients: draft.clients.map((x, i) =>
                        i === index ? { ...x, mount_path: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                文件系统名前缀
                <input
                  value={item.fs_name}
                  onChange={(e) =>
                    change({
                      clients: draft.clients.map((x, i) =>
                        i === index ? { ...x, fs_name: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                缓存组
                <input
                  value={String(item.client_conf["--cache_group"] || "")}
                  onChange={(e) =>
                    change({
                      clients: draft.clients.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              client_conf: {
                                ...x.client_conf,
                                "--cache_group": e.target.value,
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
            </div>
            <label>
              dingo 工具路径（可选）
              <input
                value={item.dingo_tool_path || ""}
                onChange={(e) =>
                  change({
                    clients: draft.clients.map((x, i) =>
                      i === index
                        ? { ...x, dingo_tool_path: e.target.value }
                        : x,
                    ),
                  })
                }
              />
            </label>
            <FlagEditor
              value={item.client_conf}
              onChange={(client_conf) =>
                change({
                  clients: draft.clients.map((x, i) =>
                    i === index ? { ...x, client_conf } : x,
                  ),
                })
              }
            />
            <button
              type="button"
              onClick={() =>
                change({ clients: draft.clients.filter((_, i) => i !== index) })
              }
            >
              移除客户端配置
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            change({
              clients: [
                ...draft.clients,
                {
                  machine_id: draft.machine_id,
                  client_count: 1,
                  mount_path: draft.mount_root,
                  fs_name: draft.fs_prefix,
                  client_conf: {},
                },
              ],
            })
          }
        >
          添加客户端配置
        </button>
      </section>
      <section>
        <h3>远程缓存配置</h3>
        <p>每项指定机器和成员数量；MDS 地址自动使用所选集群。</p>
        {draft.remote_caches.map((item, index) => (
          <div className="functional-environments-member" key={index}>
            <div className="functional-environments-fields">
              <label>
                缓存机器
                <select
                  value={item.machine_id}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index ? { ...x, machine_id: e.target.value } : x,
                      ),
                    })
                  }
                >
                  <option value="">选择机器</option>
                  {machines
                    .filter((x) => x.can_manage)
                    .map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.name} · {x.address}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                成员数
                <input
                  type="number"
                  min="1"
                  value={item.remote_cache_count}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? { ...x, remote_cache_count: Number(e.target.value) }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                缓存组
                <input
                  value={String(item.remote_cache_conf["--group_name"] || "")}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              remote_cache_conf: {
                                ...x.remote_cache_conf,
                                "--group_name": e.target.value,
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                缓存目录
                <input
                  value={String(item.remote_cache_conf["--cache_dir"] || "")}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              remote_cache_conf: {
                                ...x.remote_cache_conf,
                                "--cache_dir": e.target.value,
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                监听 IP
                <input
                  value={String(item.remote_cache_conf["--listen_ip"] || "")}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              remote_cache_conf: {
                                ...x.remote_cache_conf,
                                "--listen_ip": e.target.value,
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                起始端口
                <input
                  type="number"
                  min="1"
                  max="65535"
                  value={Number(
                    item.remote_cache_conf["--listen_port"] || 12000,
                  )}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              remote_cache_conf: {
                                ...x.remote_cache_conf,
                                "--listen_port": Number(e.target.value),
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                容量 MiB
                <input
                  type="number"
                  min="1"
                  value={Number(
                    item.remote_cache_conf["--cache_size_mb"] || 1024,
                  )}
                  onChange={(e) =>
                    change({
                      remote_caches: draft.remote_caches.map((x, i) =>
                        i === index
                          ? {
                              ...x,
                              remote_cache_conf: {
                                ...x.remote_cache_conf,
                                "--cache_size_mb": Number(e.target.value),
                              },
                            }
                          : x,
                      ),
                    })
                  }
                />
              </label>
            </div>
            <label>
              dingo 工具路径（可选）
              <input
                value={item.dingo_tool_path || ""}
                onChange={(e) =>
                  change({
                    remote_caches: draft.remote_caches.map((x, i) =>
                      i === index
                        ? { ...x, dingo_tool_path: e.target.value }
                        : x,
                    ),
                  })
                }
              />
            </label>
            <FlagEditor
              value={item.remote_cache_conf}
              onChange={(remote_cache_conf) =>
                change({
                  remote_caches: draft.remote_caches.map((x, i) =>
                    i === index ? { ...x, remote_cache_conf } : x,
                  ),
                })
              }
            />
            <button
              type="button"
              onClick={() =>
                change({
                  remote_caches: draft.remote_caches.filter(
                    (_, i) => i !== index,
                  ),
                })
              }
            >
              移除缓存配置
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            change({
              remote_caches: [
                ...draft.remote_caches,
                {
                  machine_id: draft.machine_id,
                  remote_cache_count: 1,
                  remote_cache_conf: {
                    "--group_name": "platform-cache",
                    "--cache_dir": "/tmp/dingofs-cache",
                    "--listen_port": 12000,
                    "--cache_size_mb": 1024,
                  },
                },
              ],
            })
          }
        >
          添加缓存配置
        </button>
      </section>
      <details>
        <summary>高级：指定目标机二进制</summary>
        <div className="functional-environments-fields">
          {["dingo-client", "dingo-cache", "dingo-mds-client"].map((key) => (
            <label key={key}>
              {key}
              <input
                value={draft.binaries[key] || ""}
                placeholder="留空使用集群默认"
                onChange={(e) =>
                  change({
                    binaries: { ...draft.binaries, [key]: e.target.value },
                  })
                }
              />
            </label>
          ))}
        </div>
      </details>
      <p>
        预计创建{" "}
        {draft.clients.length
          ? draft.clients.reduce((n, x) => n + x.client_count, 0)
          : 1}{" "}
        个客户端、
        {draft.remote_caches.reduce((n, x) => n + x.remote_cache_count, 0)}{" "}
        个缓存成员；测试启动后才创建文件系统和挂载点。
      </p>
      <div className="functional-environments-save">
        <button
          disabled={
            busy ||
            !draft.name.trim() ||
            !draft.cluster_id ||
            !draft.machine_id ||
            !draft.storage_profile_id ||
            draft.clients.some(
              (x) =>
                !x.machine_id ||
                !Number.isInteger(x.client_count) ||
                x.client_count < 1,
            ) ||
            draft.remote_caches.some(
              (x) =>
                !x.machine_id ||
                !Number.isInteger(x.remote_cache_count) ||
                x.remote_cache_count < 1,
            )
          }
          onClick={() => void save()}
        >
          保存测试环境
        </button>
        <button onClick={close}>取消</button>
      </div>
    </fieldset>
  );
}
