import { test, expect } from "@playwright/test";

test("official Badou appears on login and animates only while commands run", async ({
  page,
}) => {
  let loggedIn = false;
  let finished = false;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const operation = () => ({
    id: "op",
    action: "cache.list",
    state: finished ? "succeeded" : "running",
    created_at: "2026-10-10T00:00:00Z",
    result: {},
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill(
        loggedIn
          ? {
              json: {
                id: "u",
                username: "admin",
                email: "a@example.test",
                role: "admin",
                csrf_token: "test",
              },
            }
          : { status: 401, json: {} },
      );
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          external_name: "main-dingofs",
          revision: 1,
          creator_id: "u",
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources"))
      return route.fulfill({
        json: {
          catalog: [
            {
              action: "cache.list",
              label: "查询缓存组",
              section: "cache",
              fields: [],
              mutating: false,
            },
          ],
          resources: [],
          machines: [],
          operations: [operation()],
        },
      });
    if (path.endsWith("/resource-operations/op"))
      return route.fulfill({ json: operation() });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(
    page.getByRole("img", { name: "八斗 · 九章云极吉祥物" }),
  ).toBeVisible();
  expect(
    (await page.request.get("/brand/badou-official-luckybag.jpg")).ok(),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/badou-login.png" });
  loggedIn = true;
  await page.goto("/#/clusters/c1/resources");
  await page.reload();
  const indicator = page.getByRole("status", { name: "命令执行中" });
  await expect(indicator).toBeVisible();
  await expect(indicator.getByRole("img")).toBeVisible();
  await expect(indicator.locator("svg")).toHaveCSS(
    "animation-name",
    "badou-hop",
  );
  await expect(indicator).toHaveCSS("pointer-events", "none");
  await page.screenshot({ path: "/tmp/badou-running.png" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(indicator.locator("svg")).toHaveCSS("animation-name", "none");
  finished = true;
  await expect(indicator).toHaveCount(0);
  await expect(
    page.getByRole("img", { name: "八斗 · 九章云极吉祥物" }),
  ).toHaveCount(1);
  expect(errors).toEqual([]);
});
