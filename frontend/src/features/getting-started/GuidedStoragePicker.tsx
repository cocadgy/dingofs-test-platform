import { useEffect, useId, useRef, useState } from "react";
import type { StorageProfile, StorageType } from "../storage/types";

const details: Record<StorageType, [string, string][]> = {
  s3: [["Endpoint", "s3_endpoint"], ["Bucket", "s3_bucketname"]],
  rados: [["Monitor", "rados_mon"], ["Pool", "rados_poolname"], ["用户", "rados_username"], ["集群", "rados_clustername"]],
};

export function GuidedStoragePicker({ profiles, value, onChange, onAddStorage }: {
  profiles: StorageProfile[];
  value: string;
  onChange: (id: string) => void;
  onAddStorage: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [previewId, setPreviewId] = useState<string>();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const selected = profiles.find((profile) => profile.id === value);
  const preview = open ? profiles.find((profile) => profile.id === previewId) : undefined;
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) {
        setOpen(false);
        setPreviewId(undefined);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);
  function close() { setOpen(false); setPreviewId(undefined); }
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
      trigger.current?.focus();
    } else if (open && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const options = Array.from(list.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') || []);
      if (!options.length) return;
      const current = options.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : event.key === "ArrowDown" ? (current + 1) % options.length : (current + options.length - 1) % options.length;
      options[next].focus();
    } else if (!open && ["ArrowDown", "ArrowUp"].includes(event.key) && profiles.length) {
      event.preventDefault();
      setOpen(true);
      setTimeout(() => list.current?.querySelector<HTMLButtonElement>('[role="option"]')?.focus(), 0);
    }
  }
  return <div className="guided-storage-field" ref={root} onKeyDown={onKeyDown}>
    <span id={`${id}-label`} className="guided-storage-label">存储配置</span>
    <button ref={trigger} className="guided-storage-trigger" type="button" role="combobox" aria-labelledby={`${id}-label`} aria-haspopup="listbox" aria-controls={`${id}-list`} aria-expanded={open} disabled={!profiles.length} onClick={() => { setOpen(!open); setPreviewId(undefined); }}>
      {selected ? `${selected.name} · ${selected.storage_type.toUpperCase()}` : "请选择存储配置"}<span aria-hidden="true">▾</span>
    </button>
    {open && <div className="guided-storage-menu" id={`${id}-list`}>
      <div ref={list} role="listbox" aria-label="存储配置列表" className="guided-storage-options" onMouseLeave={() => setPreviewId(undefined)}>
        {profiles.map((profile) => <button key={profile.id} type="button" role="option" aria-selected={profile.id === value} onMouseEnter={() => setPreviewId(profile.id)} onFocus={() => setPreviewId(profile.id)} onClick={() => { onChange(profile.id); close(); trigger.current?.focus(); }}>
          {profile.name} · {profile.storage_type.toUpperCase()}
        </button>)}
      </div>
      {preview && <div role="tooltip" className="guided-storage-details">
        <strong>{preview.name} · {preview.storage_type.toUpperCase()}</strong>
        {preview.description && <p>{preview.description}</p>}
        <dl>{details[preview.storage_type].map(([label, key]) => <div key={key}><dt>{label}</dt><dd>{preview.parameters[key] || "—"}</dd></div>)}</dl>
      </div>}
    </div>}
    <button type="button" onClick={onAddStorage}>添加存储配置</button>
  </div>;
}
