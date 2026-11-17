import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { LogLoading } from "../remote/LogLoading";
import { Options, Profile, Run, active } from "./types";
import { CaseSelector } from "./CaseSelector";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";
import { FunctionalWizard } from "./FunctionalWizard";
import "./functional.css";
const route = () => window.location.hash.split("/")[2] || "";
function sameAddresses(a?: string[], b?: string[]) {
  return (
    !!a?.length &&
    !!b?.length &&
    a.length === b.length &&
    [...a].sort().every((x, i) => x === [...b].sort()[i])
  );
}
export function FunctionalPage() {
  const [page, setPage] = useState(route);
  const [options, setOptions] = useState<Options>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [drafts,setDrafts]=useState<{id:string;name:string;step:number;updated_at:string;revision:number;configuration:{cluster_id?:string;machine_id?:string}}[]>([]);
  const [draftId,setDraftId]=useState(window.location.hash.split("/")[3]||"");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [cluster, setCluster] = useState("");
  const [environment, setEnvironment] = useState("");
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [name, setName] = useState("");
  const [retries, setRetries] = useState(0);
  const [timeout, setTimeoutMinutes] = useState(120);
  const [binaries, setBinaries] = useState<Record<string, string>>({});
  const [valid, setValid] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<Run>();
  const [busy, setBusy] = useState(false);
  const initialized = useRef(false);
  const id = page && page !== "new" ? page : "";
  const profile = profiles.find((p) => p.id === environment);
  const count = Object.values(selected).reduce((n, rows) => n + rows.length, 0);
  function navigate(next: string) {
    setDetail(undefined);
    setError("");
    window.location.hash =
      "#/functional" + (next ? "/" + encodeURIComponent(next) : "");
    setPage(next);
    setDraftId("");
  }
  useEffect(() => {
    const sync = () => {
      setPage(route());
      setDraftId(window.location.hash.split("/")[3]||"");
      setError("");
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  async function refresh() {
    try {
      const [o, p] = await Promise.all([
        api<Options>("/functional/options"),
        api<Profile[]>("/functional/environments"),
      ]);
      setOptions(o);
      setProfiles(p);
      setCluster((v) => v || o.clusters[0]?.id || "");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (!page) {
      let live = true;
      let timer: ReturnType<typeof setTimeout>;
      const poll = async () => {
        try {
          const [rows, saved] = await Promise.all([api<Run[]>("/functional/runs"),api<typeof drafts>("/functional/drafts")]);
          if (live) {setRuns(rows);setDrafts(saved)}
        } catch (e) {
          if (live) setError((e as Error).message);
        } finally {
          if (live) timer = setTimeout(poll, 5000);
        }
      };
      void poll();
      return () => {
        live = false;
        clearTimeout(timer);
      };
    }
  }, [page]);
  // Select a default once; later refreshes must not overwrite the user's choice.
  useEffect(() => {
    if (!options || initialized.current) return;
    initialized.current = true;
    setEnvironment(
      profiles.find(
        (p) =>
          p.enabled &&
          p.validation !== "template" &&
          (p.source_kind === "custom"
            ? p.cluster_id === options.clusters[0]?.id
            : sameAddresses(
                p.display?.mds_addresses,
                options.clusters[0]?.mds_addresses,
              )),
      )?.id || "",
    );
  }, [options, profiles]);
  useEffect(() => {
    setValid(false);
    setProfileError("");
    if (!cluster || !environment) return;
    let live = true;
    api(
      `/functional/environments/${environment}/validate?cluster_id=${encodeURIComponent(cluster)}`,
    )
      .then(() => {
        if (live) setValid(true);
      })
      .catch((e) => {
        if (live) setProfileError((e as Error).message);
      });
    return () => {
      live = false;
    };
  }, [cluster, environment, profile?.revision]);
  useEffect(() => {
    if (!id) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    setDetail(undefined);
    const poll = async () => {
      try {
        const value = await api<Run>(
          `/functional/runs/${encodeURIComponent(id)}`,
        );
        if (live) {
          setDetail(value);
          if (active(value.state)) timer = setTimeout(poll, 3000);
        }
      } catch (e) {
        if (live) {
          setError((e as Error).message);
          timer = setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [id]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const numericValid =
    Number.isInteger(retries) &&
    retries >= 0 &&
    retries <= 5 &&
    Number.isInteger(timeout) &&
    timeout >= 1 &&
    timeout <= 1440;
  const disabledReason = !cluster
    ? "请选择测试集群"
    : !environment
      ? "请选择测试环境"
      : profileError
        ? "请修正测试环境问题"
        : !valid
          ? "正在验证测试环境"
          : !count
            ? "请至少选择一个用例"
            : !numericValid
              ? "重试次数为 0–5，超时为 1–1440 分钟"
              : "";
  async function create() {
    if (!options || disabledReason) return;
    await action(async () => {
      const run = await api<Run>("/functional/runs", "POST", {
        name: name.trim() || `功能测试 ${new Date().toLocaleString()}`,
        cluster_id: cluster,
        environment_profile_id: environment,
        environment_profile_revision: profile?.revision,
        selected: Object.fromEntries(
          Object.entries(selected).filter(([, rows]) => rows.length),
        ),
        catalog_digest: options.digest,
        retries,
        timeout_minutes: timeout,
        binaries: Object.fromEntries(
          Object.entries(binaries)
            .filter(([, value]) => value.trim())
            .map(([key, value]) => [key, value.trim()]),
        ),
      });
      navigate(run.id);
    });
  }
  return (
    <section className="functional-page">
      <header>
        <div>
          <p className="eyebrow">DINGOFS / FUNCTIONAL TESTS</p>
          <h1>
            {page === "new" ? "新建功能测试" : id ? "测试任务详情" : "功能测试"}
          </h1>
          <p>
            {page === "new"
              ? "选择环境和用例，确认实际执行配置后启动。"
              : "查看执行进度、失败用例与测试报告。"}
          </p>
        </div>
        <div className="functional-actions">
          {page ? (
            <button disabled={busy} onClick={() => navigate("")}>
              ← 返回任务列表
            </button>
          ) : (
            <button className="primary" onClick={() => navigate("new")}>
              新建测试
            </button>
          )}
        </div>
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && <LogLoading label="正在提交操作…" popup />}
      {!page ? (
        <>
          {drafts.length>0&&<section className="functional-card"><h2>未完成的测试配置</h2><div className="table-scroll"><table><thead><tr><th>草稿</th><th>当前步骤</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{drafts.map(row=><tr key={row.id}><td>{row.name}</td><td>{row.step} / 6</td><td>{new Date(row.updated_at).toLocaleString()}</td><td><button onClick={()=>{window.location.hash=`#/functional/new/${row.id}`;setPage('new');setDraftId(row.id)}}>继续配置</button><button onClick={()=>void action(async()=>{await api(`/functional/drafts/${row.id}?revision=${row.revision}`,'DELETE');setDrafts(rows=>rows.filter(item=>item.id!==row.id))})}>删除</button></td></tr>)}</tbody></table></div></section>}
          <RunList runs={runs} onOpen={navigate} />
        </>
      ) : page === "new" && options?.machines?.length ? (
        <FunctionalWizard key={draftId||'new'} options={options} draftId={draftId||undefined} onBack={()=>navigate('')} onStarted={navigate}/>
      ) : page === "new" ? (
        <>
          <fieldset className="functional-fieldset" disabled={busy}>
            <section className="functional-card">
              <h2>测试目标</h2>
              <div className="functional-form">
                <label>
                  任务名称
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="自动生成"
                  />
                </label>
                <label>
                  测试集群
                  <select
                    value={cluster}
                    onChange={(e) => {
                      setCluster(e.target.value);
                      setEnvironment("");
                      setValid(false);
                      setProfileError("");
                    }}
                  >
                    {options?.clusters.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} · {c.machine}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  测试环境
                  <select
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                  >
                    <option value="">选择测试环境</option>
                    {profiles
                      .filter(
                        (p) =>
                          p.enabled &&
                          (p.source_kind === "custom"
                            ? p.cluster_id === cluster
                            : sameAddresses(
                                p.display?.mds_addresses,
                                options?.clusters.find((c) => c.id === cluster)
                                  ?.mds_addresses,
                              )),
                      )
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ·{" "}
                          {p.source_kind === "custom" ? "自建" : "预置"}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <a href="#/configuration/test-environments">管理测试环境 →</a>
              {profileError && (
                <p role="alert" className="error">
                  环境不适用：{profileError}
                </p>
              )}
              {profile && (
                <div className="functional-target">
                  <strong>本次执行配置</strong>
                  <p>
                    环境：{profile.name} · 修订 {profile.revision} ·{" "}
                    {profile.display?.client_count ??
                      profile.settings?.clients?.reduce(
                        (n, c) => n + c.client_count,
                        0,
                      ) ??
                      1}{" "}
                    个客户端 ·{" "}
                    {profile.display?.cache_count ??
                      profile.settings?.remote_caches?.reduce(
                        (n, c) => n + c.remote_cache_count,
                        0,
                      ) ??
                      0}{" "}
                    个缓存成员
                  </p>
                  <p>
                    测试机：
                    {profile.display?.machine_name ||
                      profile.display?.client_hosts?.join("、") ||
                      "使用环境中指定的机器"}{" "}
                    · 存储：
                    {profile.display?.storage_name ||
                      profile.display?.storage_type ||
                      "使用环境存储配置"}
                  </p>
                  {profile.settings?.mount_root && (
                    <p>挂载根目录：{profile.settings.mount_root}</p>
                  )}
                  {["dingo-client", "dingo-cache", "dingo-mds-client"].map(
                    (key) => (
                      <p key={key}>
                        <code>{key}</code>：
                        {binaries[key]?.trim() ||
                          profile.settings?.binaries?.[key] ||
                          "运行时解析默认版本"}{" "}
                        <small>
                          （
                          {binaries[key]?.trim()
                            ? "本次指定"
                            : profile.settings?.binaries?.[key]
                              ? "测试环境配置"
                              : "环境 / 工具默认"}
                          ）
                        </small>
                      </p>
                    ),
                  )}
                </div>
              )}
              <details>
                <summary>高级执行设置与二进制路径</summary>
                <div className="functional-form">
                  <label>
                    失败重试次数
                    <input
                      type="number"
                      min="0"
                      max="5"
                      value={retries}
                      onChange={(e) => setRetries(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    超时（分钟）
                    <input
                      type="number"
                      min="1"
                      max="1440"
                      value={timeout}
                      onChange={(e) =>
                        setTimeoutMinutes(Number(e.target.value))
                      }
                    />
                  </label>
                  {["dingo-client", "dingo-cache", "dingo-mds-client"].map(
                    (key) => (
                      <label key={key}>
                        {key}
                        <input
                          value={binaries[key] || ""}
                          onChange={(e) =>
                            setBinaries({ ...binaries, [key]: e.target.value })
                          }
                          placeholder="留空继承环境；指定目标机器绝对路径"
                        />
                      </label>
                    ),
                  )}
                </div>
              </details>
            </section>
            <CaseSelector
              modules={options?.modules || {}}
              selected={selected}
              onChange={setSelected}
            />
            <div className="functional-submit">
              <span>{disabledReason || `将运行 ${count} 个用例`}</span>
              <button
                className="primary"
                disabled={!!disabledReason || busy}
                onClick={() => void create()}
              >
                启动 {count} 个用例
              </button>
            </div>
          </fieldset>
        </>
      ) : detail?.id === id ? (
        <RunDetail
          key={id}
          run={detail}
          busy={busy}
          onStop={() =>
            void action(async () => {
              await api(`/functional/runs/${detail.id}/stop`, "POST");
              setDetail(await api<Run>(`/functional/runs/${detail.id}`));
            })
          }
          onRerun={(failed) =>
            void action(async () => {
              const next = await api<Run>(
                `/functional/runs/${detail.id}/rerun${failed ? "?failed_only=true" : ""}`,
                "POST",
              );
              navigate(next.id);
            })
          }
        />
      ) : (
        !error && <LogLoading label="正在读取任务详情…" popup />
      )}
    </section>
  );
}
