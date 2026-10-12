import { BadouMascot } from "../../components/BadouMascot";

export function LogLoading({ label }: { label: string }) {
  return <div className="log-loading" role="status" aria-label={label}>
    <BadouMascot animated />
    <span>{label}</span>
  </div>;
}
