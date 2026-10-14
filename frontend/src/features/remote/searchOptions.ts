export type SearchOptions = {
  scan_mode: "prefix" | "full";
  per_file_mb: number;
  max_files: number;
  max_total_mb: number;
  max_hits: number;
};
export const defaultSearchOptions: SearchOptions = {
  scan_mode: "prefix", per_file_mb: 1, max_files: 200, max_total_mb: 16, max_hits: 200,
};
export function searchOptionsFromHash(hash: string): SearchOptions {
  const params = new URLSearchParams(hash.split("?", 2)[1] || "");
  const number = (key: string, low: number, high: number, fallback: number) => {
    const raw = params.get(key);
    const value = raw !== null && /^\d+$/.test(raw) ? Number(raw) : NaN;
    return Number.isSafeInteger(value) && value >= low && value <= high ? value : fallback;
  };
  return {
    scan_mode: params.get("mode") === "full" ? "full" : "prefix",
    per_file_mb: number("per_file_mb", 1, 64, defaultSearchOptions.per_file_mb),
    max_files: number("max_files", 1, 1000, defaultSearchOptions.max_files),
    max_total_mb: number("max_total_mb", 0, 1024, defaultSearchOptions.max_total_mb),
    max_hits: number("max_hits", 0, 500, defaultSearchOptions.max_hits),
  };
}
