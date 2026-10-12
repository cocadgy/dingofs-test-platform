export type LogBuffer = { text: string; truncated: boolean };
export function appendLog(
  previous: LogBuffer,
  incoming: string,
  maxLines = 5000,
  maxBytes = 5 * 1024 * 1024,
): LogBuffer {
  let text = previous.text + incoming;
  let truncated = previous.truncated;
  const lines = text.split("\n");
  if (lines.length > maxLines) {
    text = lines.slice(-maxLines).join("\n");
    truncated = true;
  }
  const bytes = new TextEncoder().encode(text);
  if (bytes.length > maxBytes) {
    let start = bytes.length - maxBytes;
    while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start++;
    text = new TextDecoder().decode(bytes.subarray(start));
    truncated = true;
  }
  return { text, truncated };
}
export function filterLog(text: string, keyword: string) {
  return keyword
    ? text
        .split("\n")
        .filter((line) => line.includes(keyword))
        .join("\n")
    : text;
}
