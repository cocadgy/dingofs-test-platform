export function remoteRoute(hash: string) {
  const question = hash.indexOf("?");
  const path = question === -1 ? hash : hash.slice(0, question);
  const params = new URLSearchParams(
    question === -1 ? "" : hash.slice(question + 1),
  );
  const match = path.match(/^#\/clusters\/([^/]+)\/(logs|terminal)\/([^/]+)$/);
  if (!match) return undefined;
  try {
    return {
      clusterId: decodeURIComponent(match[1]),
      kind: match[2],
      targetId: decodeURIComponent(match[3]),
      ...(match[2] === "logs" && params.has("search") && params.has("match")
        ? { searchKeyword: params.get("search")!, searchFile: params.get("match")!, searchCaseSensitive: params.get("case") === "1" }
        : {}),
      ...(match[2] === "logs" && params.has("file")
        ? { fileName: params.get("file")! }
        : {}),
    };
  } catch {
    return undefined;
  }
}
