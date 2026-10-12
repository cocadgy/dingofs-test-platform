import { useMemo, type ReactNode } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-yaml";

Prism.manual = true;
function renderTokens(
  value: string | Prism.Token | (string | Prism.Token)[],
): ReactNode {
  if (typeof value === "string") return value;
  if (Array.isArray(value))
    return value.map((part, index) => (
      <span key={index}>{renderTokens(part)}</span>
    ));
  const aliases = value.alias
    ? Array.isArray(value.alias)
      ? value.alias
      : [value.alias]
    : [];
  return (
    <span className={["token", value.type, ...aliases].join(" ")}>
      {renderTokens(value.content)}
    </span>
  );
}

export function YamlCode({ text }: { text: string }) {
  const content = useMemo(
    () => renderTokens(Prism.tokenize(text, Prism.languages.yaml)),
    [text],
  );
  return (
    <pre className="cluster-raw yaml-code" aria-label="topology.yaml 内容">
      <code>{content}</code>
    </pre>
  );
}
