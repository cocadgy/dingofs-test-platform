import { useState } from "react";
import { candidates } from "./matrix";

function magnitude(value: string): number {
  const match = /^(0|[1-9][0-9]*)([KMGTPE]?)(?:i?B)?$/i.exec(value);
  if (!match) return NaN;
  return (
    Number(match[1]) *
    1024 ** (match[2] ? "KMGTPE".indexOf(match[2].toUpperCase()) + 1 : 0)
  );
}
function equivalent(a: string, b: string) {
  return (
    a === b || (Number.isFinite(magnitude(a)) && magnitude(a) === magnitude(b))
  );
}
function ordered(values: string[]): string[] {
  const unique = values.filter(
    (v, i) => values.findIndex((x) => equivalent(x, v)) === i,
  );
  return unique.sort(
    (a, b) =>
      magnitude(a) - magnitude(b) ||
      a.localeCompare(b, undefined, { numeric: true }),
  );
}
export function CandidateInput({
  label,
  value,
  choices,
  onChange,
  defaultUnit,
}: {
  defaultUnit?: string;
  label: string;
  value: string;
  choices: string[];
  onChange: (value: string) => void;
}) {
  const values = ordered(candidates(value));
  const [unit, setUnit] = useState(defaultUnit || "");
  const [draft, setDraft] = useState("");
  const [custom, setCustom] = useState<string[]>([]);
  const [error, setError] = useState("");
  const options = ordered([...choices, ...custom, ...values]);
  const update = (next: string[]) => onChange(ordered(next).join(", "));
  const remove = (v: string) => update(values.filter((x) => !equivalent(x, v)));
  function add() {
    const number = draft.trim();
    if (!number) return;
    if (!/^(0|[1-9][0-9]*)$/.test(number)) {
      setError("每次添加一个数值，只输入整数；单位请在下拉框选择。");
      return;
    }
    const raw = number + unit;
    if (!Number.isSafeInteger(magnitude(raw))) {
      setError("数值超出支持范围，请输入更小的整数。");
      return;
    }
    const added = options.find((v) => equivalent(v, raw)) || raw;
    if (!choices.some((v) => equivalent(v, added)))
      setCustom((old) => ordered([...old, added]));
    update([...values, added]);
    setDraft("");
    setError("");
  }
  return (
    <div className="performance-candidates">
      <div className="performance-parameter-label">{label}</div>
      <div className="performance-tag-field" role="group" aria-label={label}>
        <ul className="performance-selected-tags" aria-label={label + "已选值"}>
          {values.map((v) => (
            <li key={v} data-value={v}>
              <span>{v}</span>
              <button
                type="button"
                aria-label={"删除 " + label + " " + v}
                title="删除已选参数"
                onClick={() => remove(v)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        {!values.length && (
          <span className="muted">请选择下方参数或添加自定义值</span>
        )}
      </div>
      <div className="performance-presets" aria-label={label + "常用值"}>
        {options.map((v) => (
          <span key={v} className="performance-custom-option">
            <button
              type="button"
              aria-pressed={values.some((x) => equivalent(x, v))}
              onClick={() =>
                values.some((x) => equivalent(x, v))
                  ? remove(v)
                  : update([...values, v])
              }
            >
              {v}
            </button>
            {!choices.some((x) => equivalent(x, v)) && (
              <button
                type="button"
                aria-label={"移除自定义值 " + v}
                title="移除此自定义选项"
                onClick={() => {
                  setCustom((old) => old.filter((x) => !equivalent(x, v)));
                  remove(v);
                }}
              >
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      <div className="performance-custom-add">
        <input
          aria-label={label + "自定义值"}
          value={draft}
          inputMode="numeric"
          placeholder="输入数字"
          onChange={(e) => {
            setDraft(e.target.value);
            setError("");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        {defaultUnit && (
          <select
            className="performance-unit-select"
            aria-label={label + "单位"}
            value={unit}
            onChange={(e) => {
              setUnit(e.target.value);
              setError("");
            }}
          >
            {["B", "KiB", "MiB", "GiB", "TiB", "PiB"].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          aria-label={"添加 " + label + "自定义值"}
          disabled={!draft.trim()}
          onClick={add}
        >
          ＋ 自定义添加
        </button>
      </div>
      {error && (
        <small className="error" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}
