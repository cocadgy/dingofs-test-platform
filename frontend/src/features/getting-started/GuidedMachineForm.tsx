import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { bytes } from "../inventory/MachineHardware";

type Machine = {
  id: string;
  name: string;
  address: string;
  ssh_port: number;
  ssh_user: string;
  collection_status: string;
  last_success_at?: string | null;
  hardware_info?: {
    cpu?: { logical_cores?: number } | null;
    memory?: { total_bytes?: number } | null;
    disks?: { type: string }[] | null;
    rdma?: unknown[] | null;
  } | null;
};

export function GuidedMachineForm({ onDirty, onBack, onCreated }: { onDirty: (value: boolean) => void; onBack: () => void; onCreated?: (id: string) => void }) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("22");
  const [sshUser, setSshUser] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Machine | null>(null);
  const mounted = useRef(true);
  const first = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => () => { mounted.current = false; onDirty(false); }, [onDirty]);
  useEffect(() => { if (result) heading.current?.focus(); }, [result]);
  function changed(set: (value: string) => void, value: string) {
    set(value);
    onDirty(true);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!name.trim() || !address.trim() || !sshUser.trim() || !password || !Number.isInteger(Number(port)) || Number(port) < 1 || Number(port) > 65535 || !/^[a-zA-Z0-9_.-]+$/.test(sshUser)) {
      setError("请检查必填项、SSH 用户和端口");
      first.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const machine = await api<Machine>("/guided/machines", "POST", {
        name: name.trim(), address: address.trim(), ssh_port: Number(port), ssh_user: sshUser.trim(), ssh_password: password,
      });
      if (!mounted.current) return;
      setPassword("");
      setResult(machine);
      onDirty(false);
    } catch (cause) {
      if (!mounted.current) return;
      setPassword("");
      const message = cause instanceof ApiError || cause instanceof Error ? cause.message : "连接检查失败，请重试";
      setError(message.includes(password) && password ? "连接检查失败，请重试" : message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  if (result) {
    const info = result.hardware_info;
    return <section className="getting-started-card" aria-label="添加结果">
      <h2 ref={heading} tabIndex={-1}>机器添加成功</h2>
      {result.collection_status === "partial" && <p role="alert">部分硬件信息未能采集，未知项目可稍后重试。</p>}
      <dl className="getting-started-summary">
        <div><dt>机器名称</dt><dd>{result.name}</dd></div>
        <div><dt>SSH 地址</dt><dd>{result.ssh_user}@{result.address}:{result.ssh_port}</dd></div>
        <div><dt>逻辑 CPU 核数</dt><dd>{info?.cpu?.logical_cores ?? "未知"}</dd></div>
        <div><dt>总内存</dt><dd>{bytes(info?.memory?.total_bytes)}</dd></div>
        <div><dt>物理磁盘数量</dt><dd>{info?.disks ? info.disks.filter((disk) => disk.type === "disk").length : "未知"}</dd></div>
        <div><dt>RDMA</dt><dd>{info?.rdma ? info.rdma.length ? "可用" : "未发现" : "未知"}</dd></div>
        <div><dt>最近采集成功</dt><dd>{result.last_success_at ? new Date(result.last_success_at).toLocaleString() : "未知"}</dd></div>
      </dl>
      <a href={`#/machines/${encodeURIComponent(result.id)}`}>查看机器详情</a>
      <button type="button" onClick={onBack}>返回开始页</button>
      {onCreated ? <button type="button" className="primary" onClick={() => onCreated(result.id)}>继续添加集群</button> : <button type="button" disabled>继续添加集群（即将支持）</button>}
    </section>;
  }
  return <form className="getting-started-card" onSubmit={submit}>
    <p className="muted">使用 SSH 密码验证连接并采集硬件信息，通过后才保存机器。</p>
    <label>机器名称<input ref={first} required maxLength={120} value={name} onChange={(event) => changed(setName, event.target.value)} /></label>
    <label>地址<input required maxLength={255} value={address} onChange={(event) => changed(setAddress, event.target.value)} /></label>
    <label>SSH 端口<input required type="number" min="1" max="65535" value={port} onChange={(event) => changed(setPort, event.target.value)} /></label>
    <label>SSH 用户<input required maxLength={80} pattern="[a-zA-Z0-9_.-]+" value={sshUser} onChange={(event) => changed(setSshUser, event.target.value)} /></label>
    <label>SSH 密码<input required type={visible ? "text" : "password"} autoComplete="new-password" value={password} onChange={(event) => changed(setPassword, event.target.value)} /></label>
    <button type="button" onClick={() => setVisible((value) => !value)}>{visible ? "隐藏密码" : "显示密码"}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {busy && <p role="status" aria-live="polite">正在检查 SSH 连接并采集硬件信息…</p>}
    <div className="getting-started-actions"><button type="button" disabled={busy} onClick={() => { setPassword(""); onDirty(false); onBack(); }}>上一步</button><button className="primary" type="submit" disabled={busy}>{busy ? "检查中…" : "检查连接并添加"}</button></div>
  </form>;
}
