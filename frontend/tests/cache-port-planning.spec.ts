import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const catalog = JSON.parse(
  readFileSync(
    new URL("./fixtures/resource-catalog.json", import.meta.url),
    "utf8",
  ),
) as any[];
test("auto port planning, manual choice, confirmation cancellation and creation", async ({
  page,
}) => {
  const submitted: any[] = [];
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const create: any = structuredClone(
    catalog.find((item) => item.action === "cache.create"),
  );
  const snapshot: any = {
    catalog: [
      create,
      {
        ...create,
        action: "cache.plan",
        label: "检查缓存成员端口",
        mutating: false,
      },
    ],
    machines: [
      {
        id: "m1",
        name: "测试机",
        address: "192.0.2.1",
        ssh_user: "jenkins",
        can_manage: true,
      },
    ],
    resources: [],
    operations: [],
  };
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u1",
          username: "admin",
          email: "admin@example.test",
          role: "admin",
          csrf_token: "x",
        },
      });
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          name: "测试",
          external_name: "main",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources")) return route.fulfill({ json: snapshot });
    if (path.endsWith("/resource-operations") && req.method() === "POST") {
      const body = req.postDataJSON();
      submitted.push(body);
      const op: any = {
        id: body.action === "cache.plan" ? "p1" : "c2",
        action: body.action,
        state: "succeeded",
        payload: body.parameters,
        created_at: new Date().toISOString(),
        result: {
          steps: [
            {
              data: {
                effective_port: 21003,
                planned_port: 21003,
                member: {
                  machine_id: "m1",
                  target_user: "jenkins",
                  listen_ip: "192.0.2.1",
                  listen_port: 21003,
                  cache_dir: "/tmp/cache/member-uuid",
                  cache_size_mb: 1024,
                },
              },
            },
          ],
        },
      };
      snapshot.operations.unshift(op);
      return route.fulfill({ json: op });
    }
    return route.fulfill({
      status: 500,
      json: { message: "unexpected API " + path },
    });
  });
  await page.goto("/#/clusters/c1/resources");
  await page
    .getByRole("navigation", { name: "资源功能" })
    .getByRole("button", { name: /缓存组/ })
    .click();
  await page.getByLabel("缓存组名称", { exact: true }).fill("same-group");
  await page
    .getByRole("combobox", { name: "成员 1 机器", exact: true })
    .selectOption("m1");
  await expect(page.getByLabel("成员 1 执行用户", { exact: true })).toHaveValue(
    "jenkins",
  );
  await expect(page.getByLabel("成员 1 监听 IP", { exact: true })).toHaveValue(
    "192.0.2.1",
  );
  await expect(
    page.getByRole("combobox", { name: "成员 1 端口分配", exact: true }),
  ).toHaveValue("auto");
  await expect(page.getByLabel("成员 1 监听端口", { exact: true })).toHaveCount(
    0,
  );
  await page
    .getByRole("combobox", { name: "成员 1 端口分配", exact: true })
    .selectOption("manual");
  await expect(
    page.getByLabel("成员 1 监听端口", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "成员 1 端口分配", exact: true })
    .selectOption("auto");
  await page.getByLabel("成员 1 缓存目录", { exact: true }).fill("/tmp/cache");
  const dialogs: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  await page
    .getByRole("button", { name: "检查并创建缓存组", exact: true })
    .click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[1]).toMatchObject({
    action: "cache.create",
    parameters: { plan_id: "p1" },
    confirmed: true,
  });
  expect(dialogs).toEqual([]);
  expect(submitted.map((item) => item.action)).toEqual([
    "cache.plan",
    "cache.create",
  ]);
  expect(errors).toEqual([]);
});
