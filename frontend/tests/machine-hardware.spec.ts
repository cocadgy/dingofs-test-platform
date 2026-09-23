import { test, expect, Page } from "@playwright/test";
async function login(page: Page, name = "admin") {
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill(name);
  await page.getByLabel("密码", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "机器资源", exact: true }),
  ).toBeVisible();
}
test("machine password and hardware refresh lifecycle", async ({
  page,
  browser,
}) => {
  const name = "hardware-" + Date.now();
  await login(page);
  await page.getByRole("button", { name: "登记机器资源" }).click();
  await page.getByLabel("名称", { exact: true }).fill(name);
  await page.getByLabel("主机地址").fill(name + ".test");
  await page.getByLabel("SSH 用户", { exact: true }).fill("root");
  await page.getByLabel("SSH 密码（留空保留原密码）").fill(" secret ");
  await page.getByRole("button", { name: "保存资源" }).click();
  await expect(
    page.getByText("SSH 密码：已配置", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "编辑资源" }).click();
  await expect(page.getByLabel("SSH 密码（留空保留原密码）")).toHaveValue("");
  await page.getByRole("button", { name: "保存资源" }).click();
  await page.getByRole("button", { name: "更新机器信息" }).click();
  await expect(page.getByText("CPU Model", { exact: true })).toBeVisible();
  await expect(page.getByText("mlx5_0", { exact: true })).toBeVisible();
  await expect(page.getByText("10.0.0.1/24", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "更新机器信息" }).click();
  await expect(
    page.getByText("SSH 认证失败，请核对用户名和密码", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("CPU Model", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "test-results/machine-hardware.png",
    fullPage: true,
  });
  const context = await browser.newContext();
  const member = await context.newPage();
  await login(member, "member");
  await member.getByLabel("搜索资源名").fill(name);
  await member.getByRole("button", { name, exact: true }).click();
  await expect(member.getByText("CPU Model", { exact: true })).toBeVisible();
  await expect(
    member.getByRole("button", { name: "更新机器信息" }),
  ).toHaveCount(0);
  await context.close();
  await page.getByRole("button", { name: "编辑资源" }).click();
  await page.getByLabel("清除已保存的 SSH 密码").check();
  await page.getByRole("button", { name: "保存资源" }).click();
  await expect(
    page.getByText("SSH 密码：未配置", { exact: true }),
  ).toBeVisible();
});
