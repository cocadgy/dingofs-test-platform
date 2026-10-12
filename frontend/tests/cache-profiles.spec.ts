import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const catalog = JSON.parse(
  readFileSync(
    new URL("./fixtures/cache-parameter-catalog.json", import.meta.url),
    "utf8",
  ),
);
const actions = JSON.parse(
  readFileSync(
    new URL("./fixtures/cache-profile-actions.json", import.meta.url),
    "utf8",
  ),
);

test("create a profile, customize one run, and automatically create from its port plan", async ({
  page,
}) => {
  let profile: any;
  const operations: any[] = [];
  const requests: any[] = [];
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const makeOperation = (action: string) => ({
    id: `op-${operations.length}`,
    action,
    state: "succeeded",
    created_at: new Date(Date.now() + operations.length * 1000).toISOString(),
    result: {
      steps: [
        {
          data:
            action === "cache.list"
              ? {
                  groups: { result: { group_names: [] } },
                  members: { result: { members: [] } },
                }
              : {
                  effective_port: 21000,
                  member: {
                    machine_id: "m",
                    target_user: "root",
                    listen_ip: "192.0.2.1",
                    listen_port: 21000,
                    cache_dir: "/mnt/cache/id",
                    cache_size_mb: 2048,
                  },
                },
        },
      ],
    },
  });
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u",
          username: "admin",
          email: "a@example.test",
          role: "admin",
          csrf_token: "test",
        },
      });
    if (path.endsWith("/cache-profiles/catalog"))
      return route.fulfill({ json: catalog });
    if (path.endsWith("/cache-profiles")) {
      if (req.method() === "POST") {
        profile = {
          ...req.postDataJSON(),
          id: "p",
          revision: 1,
          creator_id: "u",
          can_manage: true,
          source_version: catalog.source_version,
          updated_at: new Date().toISOString(),
        };
        return route.fulfill({ status: 201, json: profile });
      }
      return route.fulfill({ json: profile ? [profile] : [] });
    }
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          external_name: "test-cluster",
          revision: 1,
          creator_id: "u",
          binding_state: "verified",
          archived: false,
        },
      });
    if (path.endsWith("/resources"))
      return route.fulfill({
        json: {
          catalog: actions,
          cache_profiles: [profile],
          cache_parameter_catalog: catalog,
          resources: [],
          machines: [
            {
              id: "m",
              name: "测试机",
              address: "192.0.2.1",
              ssh_user: "root",
              can_manage: true,
            },
          ],
          operations,
        },
      });
    if (path.endsWith("/resource-operations") && req.method() === "POST") {
      const body = req.postDataJSON();
      requests.push(body);
      const op = makeOperation(body.action);
      operations.unshift(op);
      return route.fulfill({ status: 202, json: op });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/#/cache-profiles");
  await expect(
    page.getByRole("heading", { name: "缓存组配置", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "新建缓存组配置", exact: true })
    .click();
  await page.getByLabel("配置名称", { exact: true }).fill("日常缓存模板");
  for (const [key, value] of Object.entries({
    shards: "4",
    cache_size_mb: "2048",
    cache_dir: "/mnt/cache",
  })) {
    await page.getByLabel("搜索参数", { exact: true }).fill(key);
    await page.getByLabel(`自定义 --${key}`, { exact: true }).check();
    await page.getByLabel(`参数 --${key}`, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(
    page.getByText("缓存组配置已保存。已有成员和已提交任务不受影响。"),
  ).toBeVisible();
  await page.getByLabel("搜索参数", { exact: true }).fill("");
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollHeight))
    .toBeLessThan(3000);
  await page.screenshot({
    path: "/tmp/cache-profiles-page.png",
    fullPage: true,
  });
  await page.goto("/#/clusters/c1/resources");
  await page
    .getByRole("navigation", { name: "资源功能" })
    .getByRole("button", { name: /^缓存组/ })
    .click();
  await page.getByRole("button", { name: "创建缓存组", exact: true }).click();
  await page
    .getByLabel("缓存组名称", { exact: true })
    .fill("test-profile-group");
  await page
    .getByRole("combobox", { name: "缓存组配置", exact: true })
    .selectOption("p");
  await page
    .getByRole("combobox", { name: "成员 1 机器", exact: true })
    .selectOption("m");
  await expect(
    page.getByLabel("成员 1 缓存容量 (MB)", { exact: true }),
  ).toHaveValue("2048");
  await page.getByText(/查看 \/ 修改本次启动参数/).click();
  await page.getByLabel("搜索参数", { exact: true }).fill("shards");
  await page.getByLabel("参数 --shards", { exact: true }).fill("2");
  await page.screenshot({
    path: "/tmp/cache-profile-create.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "检查并创建缓存组", exact: true })
    .click();
  await expect
    .poll(() => requests.some((r) => r.action === "cache.create"))
    .toBe(true);
  const plan = requests.find((r) => r.action === "cache.plan");
  expect(plan.parameters.cache_options.shards).toBe("2");
  expect(plan.parameters.members[0]).toMatchObject({
    cache_size_mb: 2048,
    cache_dir: "/mnt/cache",
  });
  expect(requests.find((r) => r.action === "cache.create").parameters).toEqual({
    plan_id: expect.any(String),
  });
  expect(profile.parameters.shards).toBe("4");
  expect(errors).toEqual([]);
});
