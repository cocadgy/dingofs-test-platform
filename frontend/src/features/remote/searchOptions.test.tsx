import { expect, test } from "vitest";
import { searchOptionsFromHash } from "./searchOptions";
test("search result link preserves full scan choices", () => {
  expect(searchOptionsFromHash("#/clusters/c/logs/s?search=error&mode=full&per_file_mb=64&max_files=500&max_total_mb=256&max_hits=500")).toEqual({
    scan_mode: "full", per_file_mb: 64, max_files: 500, max_total_mb: 256, max_hits: 500,
  });
});
test("invalid URL options fall back to bounded defaults", () => {
  expect(searchOptionsFromHash("#/clusters/c/logs/s?mode=full&max_total_mb=999999").max_total_mb).toBe(16);
});

test("unlimited scan bytes and matches survive the result link", () => {
  const options = searchOptionsFromHash("#/clusters/c/logs/s?mode=full&max_total_mb=0&max_hits=0");
  expect(options.max_total_mb).toBe(0);
  expect(options.max_hits).toBe(0);
});
