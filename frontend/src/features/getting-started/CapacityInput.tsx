import { useId } from "react";
export const capacityFactors = { MiB: 1, GiB: 1024, TiB: 1048576 };
export type CapacityUnit = keyof typeof capacityFactors;
export function CapacityInput({ value, unit = "MiB", onChange, onUnitChange }: {
  value: number; unit?: CapacityUnit; onChange: (mib: number) => void; onUnitChange: (unit: CapacityUnit) => void;
}) {
  const id = useId();
  return <div className="guided-capacity-field"><label htmlFor={id}>每节点容量</label><div className="guided-capacity-input">
    <input id={id} type="number" min={1 / capacityFactors[unit]} step="any" value={value / capacityFactors[unit]} onChange={e => onChange(Number(e.target.value) * capacityFactors[unit])} />
    <select aria-label="容量单位" value={unit} onChange={e => onUnitChange(e.target.value as CapacityUnit)}>{Object.keys(capacityFactors).map(u => <option key={u}>{u}</option>)}</select>
  </div></div>;
}
