import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const catalog = JSON.parse(
  readFileSync(new URL("./fixtures/resource-catalog.json", import.meta.url), "utf8"),
);

test("large saved query history does not block resource navigation or repeat remote queries", async ({ page }) => {
  const errors: string[] = [];
  const posts: unknown[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Similar to production history: 50 queries containing 1024 bucket IDs per FS.
  const records = Array.from({ length: 50 }, (_, index) => ({
    id: `query-${index}`,
    action: "fs.list",
    creator_id: "u1",
    state: "succeeded",
    created_at: new Date(Date.UTC(2026, 9, 8, 0, 0, 50 - index)).toISOString(),
    result: {
      steps: [{ returncode: 0, data: { result: { fs_infos: Array.from({ length: 14 }, (_, fs) => ({
        fs_name: `performance-fs-${fs}`, fs_id: fs + 1, status: "NORMAL",
        block_size: 4194304, mount_points: [],
        partition_policy: { hash: { bucket_ids: Array.from({ length: 1024 }, (_, bucket) => bucket) } },
      })) } } }],
    },
  }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: {
      id: "u1", username: "admin", email: "admin@example.test", role: "admin", csrf_token: "test",
    } });
    if (path.endsWith("/clusters/c1")) return route.fulfill({ json: {
      id: "c1", external_name: "performance-fixture", creator_id: "u1", revision: 1,
      archived: false, binding_state: "verified",
    } });
    if (path.endsWith("/resources")) return route.fulfill({ json: {
      catalog, machines: [], resources: [], operations: records,
    } });
    if (path.endsWith("/resource-operations") && request.method() === "POST") {
      posts.push(request.postDataJSON());
      return route.fulfill({ json: records[0] });
    }
    return route.fulfill({ status: 500, json: { detail: `Unexpected mock endpoint: ${path}` } });
  });
  await page.goto("/#/clusters/c1/resources");
  await expect(page.getByRole("button", { name: "刷新文件系统列表", exact: true })).toBeEnabled();
  await expect(page.getByRole("table", { name: "文件系统列表", exact: true })).toBeVisible();
  expect(await page.locator("*").count()).toBeLessThan(5000);

  await page.getByRole("button", { name: "文件系统详情", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "文件系统名称", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "删除文件系统", exact: true }).click();
  await expect(page.getByRole("button", { name: "执行删除文件系统", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "目录配额", exact: true }).click();
  await expect(page.getByRole("button", { name: "查询目录配额", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "资源功能", exact: true })
    .getByRole("button", { name: /操作记录/ }).click();
  const history = page.locator("details.resource-history-entry");
  await expect(history).toHaveCount(50);
  expect(await page.locator("*").count()).toBeLessThan(5000);
  await history.nth(1).locator(":scope > summary").click();
  await expect(history.nth(1).getByRole("table", { name: "文件系统列表", exact: true })).toBeVisible();
  const fullFields = history.nth(1).locator("details").filter({ has: page.locator("summary", { hasText: "完整字段" }) }).first();
  await fullFields.locator(":scope > summary").click();
  await expect(fullFields.getByText("bucket_ids", { exact: true })).toBeVisible();
  await fullFields.locator(":scope > summary").click();
  await expect(fullFields.getByText("bucket_ids", { exact: true })).toHaveCount(0);
  expect(await page.locator("*").count()).toBeLessThan(5000);
  expect(posts).toHaveLength(1);
  expect(errors).toEqual([]);
});
