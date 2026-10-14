import { BadouMascot } from "../../components/BadouMascot";

export function LogLoading({ label, popup = false }: { label: string; popup?: boolean }) {
  return <div className={popup ? "resource-execution-indicator" : "log-loading"} role="status" aria-label={label}>
    <BadouMascot animated size={popup ? "large" : undefined} />
    {popup ? <strong>{label}</strong> : <span>{label}</span>}
  </div>;
}
