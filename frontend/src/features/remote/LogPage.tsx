import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { LogFileTable } from "./LogFileTable";
import { LogDirectorySearch } from "./LogDirectorySearch";
import { LogLoading } from "./LogLoading";
import { appendLog, filterLog, type LogBuffer } from "./logBuffer";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { useRemoteSession } from "./useRemoteSession";
import {
  logAccessReason,
  sizeText,
  type Cursor,
  type RemoteFile,
  type RemoteTargets,
} from "./types";
const empty: LogBuffer = { text: "", truncated: false };
function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function LogPage({
  clusterId,
  serviceId,
  fileName,
}: {
  clusterId: string;
  serviceId: string;
  fileName?: string;
}) {
  const [context, setContext] = useState<{
    name: string;
    os_user: string;
    targets: RemoteTargets;
  }>();
  const [error, setError] = useState("");
  const [files, setFiles] = useState<RemoteFile[]>([]);
  const [listed, setListed] = useState(false);
  const [file, setFile] = useState<RemoteFile>();
  const [lines, setLines] = useState<100 | 500 | 1000>(500);
  const [buffer, setBuffer] = useState(empty);
  const [keyword, setKeyword] = useState("");
  const [notice, setNotice] = useState("");
  const [listTruncated, setListTruncated] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const cursor = useRef<Cursor | undefined>(undefined);
  const fileRef = useRef<RemoteFile | undefined>(undefined);
  const activePage = useRef(true);
  const output = useRef<HTMLPreElement>(null);
  const [stick, setStick] = useState(true);
  const listing = useRemoteSession({
    onResult: (row) => {
      const result = row.result || {};
      const entries = result.files || [];
      setFiles(entries);
      setListed(true);
      setListTruncated(!!result.truncated);
      if (fileName !== undefined) {
        // Each tab obtains its own fresh listing capability. Never send a URL
        // filename directly to the remote reader or borrow another tab's ID.
        const matches = entries.filter((entry) => entry.name === fileName);
        if (matches.length === 1) read(matches[0]);
        else
          setError(
            `未找到日志文件：${fileName}。请刷新列表或返回列表重新选择。`,
          );
      }
    },
  });
  const remote = useRemoteSession({
    onResult: (row) => {
      const result = row.result || {};
      if (row.kind === "read") {
        setBuffer(appendLog(empty, result.text || ""));
        cursor.current = result.cursor;
        setLoaded(true);
        setNotice(
          result.truncated
            ? "仅展示本次末尾读取范围内的内容，较早内容已截断（单次上限 1 MiB）。"
            : result.reset
              ? "文件已变化，本次读取已重置位置。"
              : "",
        );
      }
    },
    onText: (event) => {
      setBuffer((previous) => appendLog(previous, event.text));
      if (event.cursor) cursor.current = event.cursor;
      if (event.reset)
        setNotice("日志发生轮转或截断，读取位置已重置；中间可能存在缺口。");
    },
  });
  const download = useRemoteSession({
    onResult: (row) => {
      const name = fileRef.current?.name || "remote.log";
      void fetch(
        `/api/v1/remote-sessions/${encodeURIComponent(row.id)}/download`,
        { credentials: "same-origin" },
      )
        .then(async (response) => {
          if (!response.ok) {
            if (response.status === 401)
              window.dispatchEvent(new Event("session-expired"));
            let message = "远程文件下载失败";
            try {
              message = (await response.json()).message || message;
            } catch {}
            throw new Error(message);
          }
          const blob = await response.blob();
          if (activePage.current) saveBlob(blob, name);
        })
        .catch((e) => {
          if (activePage.current) setError(e.message);
        });
    },
  });
  useEffect(() => {
    activePage.current = true;
    let live = true;
    Promise.all([
      api<{ name: string; os_user: string }>(
        `/clusters/${encodeURIComponent(clusterId)}`,
      ),
      api<RemoteTargets>(
        `/clusters/${encodeURIComponent(clusterId)}/remote-targets`,
      ),
    ])
      .then(([cluster, targets]) => {
        if (!live) return;
        setContext({ ...cluster, targets });
        const service = targets.services.find((row) => row.id === serviceId);
        if (!logAccessReason(service))
          void listing.start({
            kind: "files",
            cluster_id: clusterId,
            service_id: serviceId,
          });
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
      activePage.current = false;
    };
  }, [clusterId, serviceId, listing.start]);
  useEffect(() => {
    const previous = document.title;
    document.title = `${fileName !== undefined ? fileName + " · " : ""}${context?.name || "集群"} · 服务日志`;
    return () => {
      document.title = previous;
    };
  }, [context?.name, fileName]);
  useEffect(() => {
    if (stick && output.current)
      output.current.scrollTop = output.current.scrollHeight;
  }, [buffer, stick]);
  const service = context?.targets.services.find((row) => row.id === serviceId);
  const machine = context?.targets.items.find(
    (row) => row.machine_id === service?.machine_id,
  );
  const denied = context ? logAccessReason(service) : "";
  function read(next: RemoteFile, count = lines) {
    download.close();
    setFile(next);
    fileRef.current = next;
    cursor.current = undefined;
    setLoaded(false);
    setBuffer(empty);
    setNotice("");
    setError("");
    void remote.start({
      kind: "read",
      cluster_id: clusterId,
      service_id: serviceId,
      file_id: next.file_id,
      lines: count,
    });
  }
  const following = remote.active && remote.session?.kind === "log-follow";
  return (
    <>
      <header className="page-header remote-header">
        <div>
          <p className="eyebrow">PLATFORM / SERVICE LOGS</p>
          <h1>{context?.name || "集群"} · 服务日志</h1>
          <p>
            {serviceId} · {service?.role || "—"}
          </p>
        </div>
        <div className="actions">
          {fileName !== undefined && (
            <a
              className="button"
              href={`#/clusters/${encodeURIComponent(clusterId)}/logs/${encodeURIComponent(serviceId)}`}
            >
              返回日志列表
            </a>
          )}
          <a
            className="button"
            href={`#/clusters/${encodeURIComponent(clusterId)}`}
          >
            返回集群详情
          </a>
        </div>
      </header>
      <section className="panel remote-context">
        <dl>
          <div>
            <dt>目标机器</dt>
            <dd>
              {machine
                ? `${machine.name} · ${machine.address}`
                : service?.host || "—"}
            </dd>
          </div>
          <div>
            <dt>读取用户</dt>
            <dd>{remote.session?.target_user || context?.os_user || "—"}</dd>
          </div>
          <div>
            <dt>日志目录</dt>
            <dd>
              <code>{service?.log_dir || "未提供"}</code>
            </dd>
          </div>
        </dl>
      </section>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!context && !error && <LogLoading label="正在读取日志目标…" />}
      {denied ? (
        <section className="panel">
          <p role="alert">{denied}</p>
        </section>
      ) : (
        context && (
          <>
            <div className="remote-log-layout remote-log-directory">
              <section className="panel remote-files">
                <div className="section-title">
                  <h2>{fileName === undefined ? "日志文件" : "文件访问"}</h2>
                  <button
                    disabled={
                      listing.active || remote.active || download.active
                    }
                    onClick={() => {
                      setFile(undefined);
                      fileRef.current = undefined;
                      setBuffer(empty);
                      setLoaded(false);
                      setListed(false);
                      setNotice("");
                      setError("");
                      remote.close();
                      download.close();
                      void listing.start({
                        kind: "files",
                        cluster_id: clusterId,
                        service_id: serviceId,
                      });
                    }}
                  >
                    {fileName === undefined ? "刷新列表" : "重新查找文件"}
                  </button>
                </div>
                <p className="muted">
                  {fileName === undefined
                    ? "单击选中，双击或按 Enter 在新标签页查看。点击列名切换排序。"
                    : `文件名：${fileName}`}
                </p>
                <RemoteSessionStatus remote={listing} />
                {listing.active && <LogLoading label="正在读取日志文件列表…" />}
                {fileName === undefined && (
                  <LogFileTable
                    files={files}
                    disabled={listing.active}
                    onOpen={(row) =>
                      window.open(
                        `#/clusters/${encodeURIComponent(clusterId)}/logs/${encodeURIComponent(serviceId)}?file=${encodeURIComponent(row.name)}`,
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  />
                )}
                {fileName === undefined && listed && !files.length && (
                  <p className="empty">目录中没有可读取的普通日志文件</p>
                )}
                {listTruncated && (
                  <p role="status">文件列表已截断，请先检查远程目录。</p>
                )}
              </section>
              {fileName === undefined && <LogDirectorySearch clusterId={clusterId} serviceId={serviceId} fileUrl={name => `#/clusters/${encodeURIComponent(clusterId)}/logs/${encodeURIComponent(serviceId)}?file=${encodeURIComponent(name)}`} />}
              {fileName !== undefined && (
                <section className="panel remote-log-main">
                  <div className="section-title">
                    <h2>{file?.name || fileName}</h2>
                    {following && <span className="badge">实时追踪</span>}
                  </div>
                  <div className="remote-log-toolbar">
                    <label>
                      末尾行数
                      <select
                        aria-label="末尾行数"
                        value={lines}
                        disabled={remote.active}
                        onChange={(e) => {
                          const next = Number(e.target.value) as
                            100 | 500 | 1000;
                          setLines(next);
                          if (file) read(file, next);
                        }}
                      >
                        <option value={100}>100 行</option>
                        <option value={500}>500 行</option>
                        <option value={1000}>1000 行</option>
                      </select>
                    </label>
                    <button
                      disabled={!file || remote.active}
                      onClick={() => file && read(file)}
                    >
                      重新读取
                    </button>
                    {following ? (
                      <button onClick={remote.close}>暂停追踪</button>
                    ) : (
                      <button
                        className="primary"
                        disabled={!file || !loaded || remote.active}
                        onClick={() =>
                          file &&
                          remote.start({
                            kind: "log-follow",
                            cluster_id: clusterId,
                            service_id: serviceId,
                            file_id: file.file_id,
                            lines,
                            ...(cursor.current
                              ? { cursor: cursor.current }
                              : {}),
                          })
                        }
                      >
                        实时追踪
                      </button>
                    )}
                    <label>
                      过滤当前内容
                      <input
                        aria-label="过滤当前内容"
                        placeholder="字面量关键词"
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                      />
                    </label>
                  </div>
                  <RemoteSessionStatus remote={remote} />
                  {remote.active && remote.session?.kind === "read" && <LogLoading label="正在读取日志…" />}
                  {notice && (
                    <p className="remote-notice" role="status">
                      {notice}
                    </p>
                  )}
                  {buffer.truncated && (
                    <p className="remote-notice" role="status">
                      缓冲区达到 5000 行或 5 MiB 上限，最早内容已移除。
                    </p>
                  )}
                  <pre
                    aria-label="日志内容"
                    className="remote-log-output"
                    ref={output}
                    tabIndex={0}
                    onScroll={(e) => {
                      const node = e.currentTarget;
                      setStick(
                        node.scrollHeight - node.scrollTop - node.clientHeight <
                          40,
                      );
                    }}
                  >
                    {filterLog(buffer.text, keyword)}
                  </pre>
                  <div className="actions remote-downloads">
                    <button
                      disabled={!buffer.text}
                      onClick={() =>
                        saveBlob(
                          new Blob([buffer.text], {
                            type: "text/plain;charset=utf-8",
                          }),
                          `${file?.name || "log"}.loaded.txt`,
                        )
                      }
                    >
                      下载当前内容
                    </button>
                    <button
                      disabled={
                        !file ||
                        file.size > 100 * 1024 * 1024 ||
                        download.active
                      }
                      onClick={() =>
                        file &&
                        download.start({
                          kind: "download",
                          cluster_id: clusterId,
                          service_id: serviceId,
                          file_id: file.file_id,
                        })
                      }
                    >
                      下载远程文件
                    </button>
                    <button
                      disabled={stick}
                      onClick={() => {
                        setStick(true);
                        if (output.current)
                          output.current.scrollTop =
                            output.current.scrollHeight;
                      }}
                    >
                      滚动到底部
                    </button>
                  </div>
                  <p className="muted">
                    过滤仅作用于当前缓冲内容。当前内容下载保留缓冲区原文；远程文件下载上限
                    100 MiB，按开始时的文件长度读取。
                    {file && file.size > 100 * 1024 * 1024
                      ? ` 当前文件 ${sizeText(file.size)}，超出下载上限。`
                      : ""}
                  </p>
                  {download.session && (
                    <RemoteSessionStatus remote={download} />
                  )}
                </section>
              )}
            </div>
          </>
        )
      )}
    </>
  );
}
