export function highlightKeyword(text: string, keyword: string, sensitive: boolean) {
  if (!keyword) return text;
  const source = sensitive ? text : text.toLocaleLowerCase();
  const needle = sensitive ? keyword : keyword.toLocaleLowerCase();
  const parts: React.ReactNode[] = [];
  let start = 0;
  while (start < text.length) {
    const found = source.indexOf(needle, start);
    if (found < 0) break;
    parts.push(text.slice(start, found), <mark key={found}>{text.slice(found, found + keyword.length)}</mark>);
    start = found + keyword.length;
  }
  parts.push(text.slice(start));
  return parts;
}
