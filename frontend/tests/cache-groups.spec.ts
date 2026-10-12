import { test, expect } from "@playwright/test";

test("MDS stopped groups replace failed local attempts in the inventory and count", async ({
  page,
}) => {
  const names = Array.from(
    { length: 30 },
    (_, i) => `vdbench_cache_group-${i}`,
  );
  const members = names.flatMap((group_name, i) =>
    [0, 1].map((n) => ({
      group_name,
      member_id: `member-${i}-${n}`,
      ip: "192.0.2.1",
      port: 21000 + n,
      state: 3,
    })),
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
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
          name: "测试",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources"))
      return route.fulfill({
        json: {
          machines: [],
          catalog: [
            {
              action: "cache.list",
              label: "缓存组与成员列表",
              section: "cache",
              mutating: false,
              fields: [],
            },
          ],
          resources: [
            {
              id: "attempt",
              kind: "cache",
              name: "test1",
              state: "deleted",
              created_at: "2026-10-09",
              data: { members: [{}] },
            },
          ],
          operations: [
            {
              id: "query",
              action: "cache.list",
              state: "succeeded",
              created_at: "2026-10-09T07:22:14Z",
              result: {
                steps: [
                  {
                    returncode: 0,
                    data: {
                      groups: { result: { group_names: names } },
                      members: { result: { members } },
                    },
                  },
                ],
              },
            },
          ],
        },
      });
    return route.fulfill({ status: 500, json: { detail: "unexpected API" } });
  });
  await page.goto("/#/clusters/c1/resources");
  const nav = page.getByRole("navigation", { name: "资源功能", exact: true });
  const tab = nav.getByRole("button", { name: /缓存组/ });
  await expect(tab).toContainText("30");
  await tab.click();
  const table = page.getByRole("table", { name: "缓存组列表", exact: true });
  await expect(table.locator(":scope > tbody > tr")).toHaveCount(30);
  await expect(
    table.getByRole("cell", { name: "已停止", exact: true }),
  ).toHaveCount(30);
  await expect(table.getByText("test1", { exact: true })).toHaveCount(0);
  await page
    .getByRole("searchbox", { name: "搜索资源", exact: true })
    .fill("vdbench_cache_group-29");
  await expect(table.locator(":scope > tbody > tr")).toHaveCount(1);
  await table.getByText("成员信息", { exact: true }).click();
  await expect(table.getByText("member-29-0", { exact: true })).toBeVisible();
  await expect(
    table.getByText("192.0.2.1:21000", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("queried-cache-groups.png"),
    fullPage: false,
  });
  expect(errors).toEqual([]);
});
