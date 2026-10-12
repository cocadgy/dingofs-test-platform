/** Shell-style filename patterns, without invoking a shell or expanding variables.
 * Memoized matching bounds work by pattern length times name length.
 */
export function shellMatches(pattern: string, name: string): boolean {
  if (!pattern || (name.startsWith(".") && !pattern.startsWith(".")))
    return false;
  const memo = new Map<string, boolean>();
  function match(p: number, n: number): boolean {
    const key = `${p}:${n}`;
    const cached = memo.get(key);
    if (cached !== undefined) return cached;
    let result = false;
    const char = pattern[p];
    if (p === pattern.length) result = n === name.length;
    else if (char === "*")
      result = match(p + 1, n) || (n < name.length && match(p, n + 1));
    else if (n < name.length) {
      if (char === "?") result = match(p + 1, n + 1);
      else if (char === "\\" && p + 1 < pattern.length)
        result = pattern[p + 1] === name[n] && match(p + 2, n + 1);
      else if (char === "[") {
        let start = p + 1;
        const negate = pattern[start] === "!" || pattern[start] === "^";
        if (negate) start++;
        let end = start;
        if (pattern[end] === "]") end++;
        while (end < pattern.length && pattern[end] !== "]") end++;
        if (end === pattern.length)
          result = char === name[n] && match(p + 1, n + 1);
        else {
          let included = false;
          for (let i = start; i < end; i++) {
            if (i + 2 < end && pattern[i + 1] === "-") {
              included ||= name[n] >= pattern[i] && name[n] <= pattern[i + 2];
              i += 2;
            } else included ||= pattern[i] === name[n];
          }
          result = (negate ? !included : included) && match(end + 1, n + 1);
        }
      } else result = char === name[n] && match(p + 1, n + 1);
    }
    memo.set(key, result);
    return result;
  }
  return match(0, 0);
}
