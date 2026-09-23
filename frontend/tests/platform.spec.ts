import { test, expect, Page } from "@playwright/test";
async function login(page: Page, user = "admin") {
  await page.goto("/");
  await page.getByLabel("用户名").fill(user);
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.PLATFORM_E2E_PASSWORD || "test-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "机器资源", exact: true }),
  ).toBeVisible();
}
async function nav(page: Page, label: string) {
  await page
    .getByRole("navigation")
    .getByRole("button", { name: label })
    .click();
}
async function register(
  page: Page,
  section: string,
  values: Record<string, string>,
  refs: Record<string, string> = {},
) {
  await nav(page, section);
  await page
    .getByRole("button", { name: "登记" + section, exact: true })
    .click();
  for (const [label, value] of Object.entries(values))
    await page.getByLabel(label, { exact: true }).fill(value);
  for (const [label, value] of Object.entries(refs))
    await page
      .getByLabel(label, { exact: true })
      .selectOption({ label: value });
  await page.getByRole("button", { name: "保存资源" }).click();
  await expect(
    page.getByRole("heading", { name: values["名称"], exact: true }),
  ).toBeVisible();
}
test("real inventory and YAML lifecycle, validation, conflict and reference protection", async ({
  page,
}) => {
  const suffix = Date.now();
  const machine = "e2e-node-" + suffix,
    cluster = "e2e-cluster-" + suffix,
    env = "e2e-env-" + suffix;
  await login(page);
  await register(page, "机器资源", {
    名称: machine,
    主机地址: "node-" + suffix + ".example",
    "SSH 用户": "tester",
    "SSH 密码（留空保留原密码）": "test-ssh-password",
  });
  await expect(
    page.getByRole("navigation").getByRole("button", { name: "管理上下文" }),
  ).toHaveCount(0);
  await nav(page, "集群管理");
  await page.getByRole("button", { name: "发现集群", exact: true }).click();
  await page
    .getByLabel("执行机器")
    .selectOption({ label: machine + " · node-" + suffix + ".example" });
  await page.getByLabel("执行用户").fill("tester");
  await page.getByRole("button", { name: "查询集群" }).click();
  await page.getByLabel("main-dingofs", { exact: true }).check();
  await page.getByRole("button", { name: "导入所选集群" }).click();
  await page.getByLabel("搜索执行用户").fill("tester");
  await page.getByRole("button", { name: "main-dingofs", exact: true }).click();
  await page.getByRole("button", { name: "编辑登记信息" }).click();
  await page.getByLabel("显示名称").fill(cluster);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: cluster, exact: true }),
  ).toBeVisible();
  await register(
    page,
    "测试环境",
    { 名称: env },
    { 关联集群: cluster, 测试机器: machine },
  );
  await page.getByRole("button", { name: "常用参数", exact: true }).click();
  await page.getByLabel("文件系统名称").fill("initial");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByRole("status")).toHaveText("草稿已保存");
  await page.getByRole("button", { name: "高级 YAML 编辑" }).click();
  await page
    .getByLabel("高级 YAML", { exact: true })
    .fill("# preserve\nfilesystem: first\nadvanced:\n  flag: true\n");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(
    page.getByRole("button", { name: "发布配置版本" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "发布配置版本" }).click();
  await expect(page.getByText("版本 1", { exact: true })).toBeVisible();
  await page.getByLabel("高级 YAML", { exact: true }).fill("filesystem: [");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByRole("alert")).toContainText("YAML");
  await expect(page.getByLabel("高级 YAML", { exact: true })).toHaveValue(
    "filesystem: [",
  );
  await expect(
    page.getByRole("button", { name: "发布配置版本" }),
  ).toBeDisabled();
  await page
    .getByLabel("高级 YAML", { exact: true })
    .fill("# preserve\nfilesystem: second\nadvanced:\n  flag: true\n");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(
    page.getByRole("button", { name: "发布配置版本" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "发布配置版本" }).click();
  await expect(page.getByText("版本 2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "对比最近两个版本" }).click();
  await expect(page.getByLabel("版本差异")).toContainText("-filesystem: first");
  const other = await page.context().newPage();
  await other.goto("/");
  await nav(other, "测试环境");
  await other.getByRole("button", { name: env + " 已登记" }).click();
  await expect(other.getByLabel("高级 YAML", { exact: true })).toBeVisible();
  await page
    .getByLabel("高级 YAML", { exact: true })
    .fill("filesystem: concurrent");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(
    page.getByRole("button", { name: "发布配置版本" }),
  ).toBeEnabled();
  await other
    .getByLabel("高级 YAML", { exact: true })
    .fill("filesystem: local");
  await other.getByRole("button", { name: "保存草稿" }).click();
  await expect(other.getByRole("alert")).toContainText("草稿已更新");
  await expect(other.getByLabel("高级 YAML", { exact: true })).toHaveValue(
    "filesystem: local",
  );
  await other.close();
  await page.reload();
  await nav(page, "测试环境");
  await page.getByRole("button", { name: env + " 已登记" }).click();
  await expect(page.getByText("版本 2", { exact: true })).toBeVisible();
  await nav(page, "机器资源");
  await page.getByLabel("搜索资源名").fill(machine);
  await page.getByRole("button", { name: machine, exact: true }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "归档资源" }).click();
  await expect(page.getByRole("alert")).toContainText("仍被引用");
  const csrf = await page.request.post("/api/v1/machines", {
    data: { name: "blocked", address: "blocked", ssh_user: "test" },
  });
  expect(csrf.status()).toBe(403);
  await page.screenshot({
    path: "test-results/platform-inventory.png",
    fullPage: true,
  });
});
test("member can register own machine but cannot change another user's machine", async ({ page }) => {
  await login(page, "member");
  await expect(page.getByRole("button", {name: "登记机器资源"})).toBeVisible();
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const headers = {"X-CSRF-Token": me.csrf_token};
  const name = "member-machine-" + Date.now();
  const result = await page.request.post("/api/v1/machines", {headers, data:{name,address:name+".test",ssh_user:"test"}});
  expect(result.status()).toBe(201);
  const owned = await result.json();
  const update = await page.request.patch(`/api/v1/machines/${owned.id}`, {headers,data:{base_revision:owned.revision,maintenance:true}});
  expect(update.status()).toBe(200);
  const rows = await (await page.request.get("/api/v1/machines?limit=200")).json();
  const other = rows.items.find((r: any) => r.creator_id !== me.id);
  expect(other).toBeTruthy();
  const denied = await page.request.patch(`/api/v1/machines/${other.id}`,{headers,data:{base_revision:other.revision,maintenance:true}});
  expect(denied.status()).toBe(403);
});
