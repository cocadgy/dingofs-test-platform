// @ts-expect-error Node types are not part of the browser build.
import { readFileSync } from "node:fs";
// @ts-expect-error Node types are not part of the browser build.
import { resolve } from "node:path";
import { expect, test } from "vitest";

test("browser tab uses the same Badou portrait as the homepage", () => {
  const root = resolve(".");
  const html = readFileSync(resolve(root, "index.html"), "utf8");
  const favicon = readFileSync(resolve(root, "public/brand/badou-favicon.svg"), "utf8");
  expect(html).toContain('href="/brand/badou-favicon.svg"');
  expect(favicon).toContain("data:image/jpeg;base64,");
  expect(favicon).toContain('viewBox="630 30 352 284"');
});
