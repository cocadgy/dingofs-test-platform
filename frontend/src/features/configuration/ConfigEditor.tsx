import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
type Draft = components["schemas"]["DraftResponse"];
type Version = { version: number; yaml_text: string; sha256: string };
export function ConfigEditor({
  kind,
  id,
  admin,
  onDirty,
}: {
  kind: string;
  id: string;
  admin: boolean;
  onDirty: (dirty: boolean) => void;
}) {
  const base = `/configs/${kind}/${id}`;
  const [draft, setDraft] = useState<Draft>();
  const [text, setText] = useState("");
  const [view, setView] = useState<"yaml" | "form">("yaml");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [versions, setVersions] = useState<Version[]>([]);
  const [diff, setDiff] = useState("");
  const [remote, setRemote] = useState<Draft>();
  const dirty =
    !!draft && (text !== draft.yaml_text || Object.keys(fields).length > 0);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    let live = true;
    Promise.all([
      api<Draft>(base + "/draft"),
      api<{ items: Version[] }>(base + "/versions"),
    ])
      .then(([d, v]) => {
        if (live) {
          setDraft(d);
          setText(d.yaml_text);
          setVersions(v.items);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [base]);
  async function save() {
    if (!draft) return;
    if (view === "form" && text !== draft.yaml_text) {
      setError("请先保存高级 YAML，再应用常用参数；当前输入已保留。");
      return;
    }
    if (view === "yaml" && Object.keys(fields).length) {
      setError("请先保存常用参数，再保存 YAML；当前输入已保留。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload: components["schemas"]["DraftInput"] = {
        base_revision: draft.revision,
        mode: view,
        ...(view === "yaml" ? { yaml_text: text } : { field_updates: fields }),
      };
      const d = await api<Draft>(base + "/draft", "PUT", payload);
      setDraft(d);
      // Keep edits made after this request was sent; only replace the submitted snapshot.
      setText((current) => current === text ? d.yaml_text : current);
      setFields((current) =>
        JSON.stringify(current) === JSON.stringify(fields) ? {} : current,
      );
      setNotice("草稿已保存");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    setBusy(true);
    setError("");
    try {
      await api(base + "/publish", "POST", { base_revision: draft!.revision });
      setVersions((await api<{ items: Version[] }>(base + "/versions")).items);
      setNotice("配置版本已发布，仅保存版本");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="config">
      <div className="section-title">
        <h2>配置与版本</h2>
        <span className="badge">工具未校验</span>
      </div>
      <p className="muted">
        保存和发布仅记录配置，不改变远端集群。请使用凭据引用，不填写密码或私钥。
      </p>
      {error && (
        <p role="alert" className="error">
          {error}{" "}
          {error.includes("更新") &&
            "可查看远端草稿后手动合并，本地输入已保留。"}
        </p>
      )}
      {error.includes("更新") && (
        <div className="actions">
          <button
            onClick={async () => {
              try {
                setRemote(await api<Draft>(base + "/draft"));
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            查看远端版本
          </button>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(
                  view === "yaml" ? text : JSON.stringify(fields, null, 2),
                );
                setNotice("本地输入已复制");
              } catch {
                setNotice("浏览器不允许复制，请在编辑框中手动复制");
              }
            }}
          >
            复制本地输入
          </button>
        </div>
      )}
      {remote && (
        <div className="remote">
          <h3>远端修订 {remote.revision}</h3>
          <pre aria-label="远端草稿">{remote.yaml_text}</pre>
          <button
            onClick={() => {
              if (confirm("确定采用远端版本？请先复制需要保留的本地修改。")) {
                setDraft(remote);
                setText(remote.yaml_text);
                setFields({});
                setRemote(undefined);
                setError("");
              }
            }}
          >
            使用远端版本
          </button>
          <button
            onClick={() => {
              setDraft(remote);
              setRemote(undefined);
              setError("");
              setNotice("已更新基准修订，请合并远端内容后保存本地修改");
            }}
          >
            保留本地输入并更新基准
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      {!draft ? (
        <p>正在加载配置…</p>
      ) : (
        <>
          <div className="tabs">
            {kind === "environment" && (
              <button
                type="button"
                onClick={() => setView("form")}
                aria-pressed={view === "form"}
              >
                常用参数
              </button>
            )}
            <button
              type="button"
              onClick={() => setView("yaml")}
              aria-pressed={view === "yaml"}
            >
              高级 YAML 编辑
            </button>
            <span>
              修订 {draft.revision} ·{" "}
              {draft.validation.syntax_valid ? "语法已校验" : "尚未保存"}
              {dirty ? " · 有未保存修改" : ""}
            </span>
          </div>
          {view === "yaml" ? (
            <label>
              高级 YAML
              <textarea
                className="yaml"
                aria-label="高级 YAML"
                value={text}
                readOnly={!admin || Object.keys(fields).length > 0}
                spellCheck={false}
                onChange={(e) => setText(e.target.value)}
              />
            </label>
          ) : (
            <div className="form-grid">
              <p className="muted">
                只更新填写的字段，保留草稿中的注释和高级配置。
              </p>
              {Object.entries({
                filesystem: "文件系统名称",
                mount_root: "挂载根目录",
                dingo_path: "dingo 工具路径",
                vdbench_path: "vdbench 路径",
              }).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={fields[key] ?? ""}
                    placeholder={
                      draft.form_values?.[key]
                        ? `当前：${draft.form_values[key]}`
                        : "留空表示不修改"
                    }
                    disabled={!admin || text !== draft.yaml_text}
                    onChange={(e) =>
                      setFields((old) => {
                        const next = { ...old };
                        if (e.target.value) next[key] = e.target.value;
                        else delete next[key];
                        return next;
                      })
                    }
                  />
                </label>
              ))}
            </div>
          )}
          {admin && (
            <div className="actions">
              <button onClick={save} disabled={busy || !dirty}>
                保存草稿
              </button>
              <button
                className="primary"
                onClick={publish}
                disabled={busy || dirty || !draft.revision}
              >
                发布配置版本
              </button>
            </div>
          )}
        </>
      )}
      <h3>版本历史</h3>
      {versions.length === 0 ? (
        <p className="muted">暂无发布版本</p>
      ) : (
        versions.map((v) => (
          <details key={v.version}>
            <summary>版本 {v.version}</summary>
            <small>SHA-256: {v.sha256}</small>
            <pre>{v.yaml_text}</pre>
          </details>
        ))
      )}
      {versions.length > 1 && (
        <button
          onClick={async () => {
            try {
              setDiff(
                (
                  await api<{ diff: string }>(
                    base +
                      `/diff?from=${versions[1].version}&to=${versions[0].version}`,
                  )
                ).diff,
              );
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          对比最近两个版本
        </button>
      )}
      {diff && (
        <pre className="diff" aria-label="版本差异">
          {diff}
        </pre>
      )}
    </section>
  );
}
