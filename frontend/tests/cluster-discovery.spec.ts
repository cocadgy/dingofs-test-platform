import { test, expect } from "@playwright/test";
test("discovery with user-switch password, same-name users, status details and history", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "集群管理" })
    .click();
  for (const user of ["root", "protected"]) {
    await page.getByRole("button", { name: "发现集群", exact: true }).click();
    await page
      .getByLabel("执行机器")
      .selectOption({ label: "overview-01 · 10.220.68.1" });
    await page.getByLabel("执行用户").fill(user);
    await page.getByRole("button", { name: "查询集群" }).click();
    if (user === "protected") {
      await expect(page.getByText("需要验证账号：root")).toBeVisible();
      await page.getByLabel("认证密码").fill("temporary-test-password");
      await page.getByRole("button", { name: "验证并继续" }).click();
    }
    await page.getByLabel("main-dingofs", { exact: true }).check();
    await page.getByRole("button", { name: "导入所选集群" }).click();
    await expect(page.getByRole("table", { name: "集群列表" })).toBeVisible();
  }
  await page.getByLabel("搜索执行用户").fill("root");
  await page.getByRole("button", { name: "main-dingofs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "服务实例" })).toBeVisible();
  await expect(page.getByText("coordinator · 3")).toBeVisible();
  await page.getByLabel("角色", { exact: true }).selectOption("mds");
  await expect(page.locator(".cluster-services tbody tr")).toHaveCount(3);
  await page.getByText("查看目录", { exact: true }).first().click();
  await expect(
    page.getByText(
      "/home/jenkins/dingofs-main/202609222021-f018b8d/logs/mds0",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByText("原始输出与查询信息").click();
  await expect(page.locator(".cluster-raw")).toContainText(
    "Get Service Status: [OK]",
  );
  const url = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "服务实例" })).toBeVisible();
  expect(page.url()).toBe(url);
  await page.getByRole("button", { name: "返回集群概览" }).click();
  await page.getByLabel("搜索执行用户").fill("protected");
  await page.getByRole("button", { name: "main-dingofs", exact: true }).click();
  await expect(page.getByText("需要验证账号：root")).toBeVisible();
  await page.getByLabel("认证密码").fill("temporary-test-password");
  await page.getByRole("button", { name: "验证并继续" }).click();
  await expect(page.getByText("coordinator · 3")).toBeVisible();
  await page.getByRole("button", { name: "返回集群概览" }).click();
  await expect(page.getByLabel("搜索执行用户")).toHaveValue("protected");
  await page.screenshot({
    path: "test-results/cluster-overview.png",
    fullPage: true,
  });
});
