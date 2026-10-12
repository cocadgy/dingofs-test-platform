import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const catalog = JSON.parse(
  readFileSync(
    new URL("./fixtures/resource-catalog.json", import.meta.url),
    "utf8",
  ),
);
async function setup(page: Page) {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  const records = [
    {
      id: "query1",
      action: "fs.list",
      state: "succeeded",
      created_at: "2026-09-28T00:00:00Z",
      creator_id: "u1",
      machine_name: "测试管理节点",
      target_user: "jenkins",
      result: {
        steps: [
          {
            returncode: 0,
            data: {
              error: { code: 0, description: "success" },
              result: {
                fs_infos: [
                  {
                    fs_id: 18056,
                    fs_name: "integration-test-main",
                    owner: "jenkins",
                    status: "NORMAL",
                    capacity: 1099511627776,
                    block_size: 4194304,
                    mount_points: [],
                  },
                ],
                info: { time: { total_time_us: 1260 } },
              },
            },
          },
        ],
      },
    },
    {
      id: "old-query",
      action: "fs.list",
      state: "failed",
      created_at: "2026-09-27T00:00:00Z",
      message: "连接超时",
      result: null,
    },
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") requests.push(path);
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u1",
          username: "admin",
          email: "admin@example.test",
          role: "admin",
          csrf_token: "test",
        },
      });
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          external_name: "main-dingofs",
          name: "集成测试环境",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources"))
      return route.fulfill({
        json: {
          catalog,
          machines: [
            {
              id: "m1",
              name: "测试管理节点",
              address: "192.0.2.1",
              ssh_user: "jenkins",
              can_manage: true,
            },
          ],
          resources: [
            {
              id: "cache1",
              kind: "cache",
              name: "shared-cache",
              state: "running",
              created_at: "2026-09-27",
              data: { members: [{ machine_id: "m1" }] },
            },
            {
              id: "mount1",
              kind: "mount",
              name: "client-01",
              state: "mounted",
              created_at: "2026-09-27",
              data: {
                machine_id: "m1",
                fs_name: "integration-test-main",
                mount_path: "/mnt/dingofs/integration",
              },
            },
          ],
          operations: records,
        },
      });
    return route.fulfill({
      status: 500,
      json: { detail: "unexpected API: " + path },
    });
  });
  await page.goto("/#/clusters/c1/resources");
  return { requests, errors };
}
test("resource workspace navigation isolates each task and history without remote execution", async ({
  page,
}) => {
  const { requests, errors } = await setup(page);
  const nav = page.getByRole("navigation", { name: "资源功能", exact: true });
  await expect(
    page.getByRole("heading", { name: "资源管理 · main-dingofs" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "文件系统列表", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("resource-redesign-filesystems.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "目录配额", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "设置目录配额", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "删除文件系统", exact: true }),
  ).toBeHidden();
  await page.screenshot({
    path: test.info().outputPath("resource-redesign-quota.png"),
    fullPage: true,
  });
  await nav.getByRole("button", { name: /缓存组/ }).click();
  await expect(
    page.getByRole("button", { name: "停止 shared-cache", exact: true }),
  ).toBeVisible();
  await nav.getByRole("button", { name: /挂载点/ }).click();
  await page
    .getByRole("button", { name: "日志 client-01", exact: true })
    .click();
  await expect(
    page.getByLabel("日志文件名（留空列出文件）", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("resource-redesign-mounts.png"),
    fullPage: true,
  });
  await nav.getByRole("button", { name: /操作记录/ }).click();
  await page
    .getByRole("combobox", { name: "操作状态", exact: true })
    .selectOption("failed");
  await expect(page.getByText("连接超时", { exact: true })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("resource-redesign-history.png"),
    fullPage: true,
  });
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});
test("mobile workspace stays within viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await expect(
    page.getByRole("navigation", { name: "资源功能", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("resource-redesign-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
