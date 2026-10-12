import { useEffect, useState, type ReactNode } from "react";

export function LazyDetails({
  summary,
  children,
  open = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  open?: boolean;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(open);
  useEffect(() => setExpanded(open), [open]);
  return (
    <details
      className={className}
      open={expanded}
      onToggle={(event) => {
        if (event.target === event.currentTarget)
          setExpanded(event.currentTarget.open);
      }}
    >
      <summary>{summary}</summary>
      {expanded ? children : null}
    </details>
  );
}
