import { test, expect, Page } from "@playwright/test";
async function login(page: Page, username: string, password: string) {
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
}
async function nav(page: Page, name: string) {
  await page
    .getByRole("navigation")
    .getByRole("button", { name, exact: false })
    .click();
}
test("admin user lifecycle and password-verified self service", async ({
  page,
  browser,
}) => {
  const username = "user-" + Date.now(),
    initial = "initial-password-123";
  await login(
    page,
    "admin",
    process.env.PLATFORM_E2E_PASSWORD || "test-password-123",
  );
  await nav(page, "用户管理");
  await page.getByRole("button", { name: "添加用户", exact: true }).click();
  await page.getByLabel("用户名", { exact: true }).fill(username);
  await page
    .getByLabel("邮箱", { exact: true })
    .fill(username + "@example.com");
  await page.getByLabel("初始密码").fill(initial);
  await page.getByRole("button", { name: "创建用户" }).click();
  await expect(page.getByRole("status")).toHaveText("用户已创建");
  const row = page.getByRole("row").filter({ hasText: username });
  await expect(row).toContainText("已启用");
  const memberContext = await browser.newContext();
  const member = await memberContext.newPage();
  await login(member, username, initial);
  await expect(
    member.getByRole("heading", { name: "机器资源", exact: true }),
  ).toBeVisible();
  await expect(
    member.getByRole("navigation").getByRole("button", { name: "用户管理" }),
  ).toHaveCount(0);
  await nav(member, "个人设置");
  await member.getByLabel("邮箱", { exact: true }).fill("changed@example.com");
  await member.getByLabel("修改邮箱的当前密码").fill("wrong");
  await member.getByRole("button", { name: "修改邮箱", exact: true }).click();
  await expect(member.getByRole("alert")).toContainText("当前密码不正确");
  await expect(member.getByLabel("邮箱", { exact: true })).toHaveValue(
    "changed@example.com",
  );
  await member.getByLabel("修改邮箱的当前密码").fill(initial);
  await member.getByRole("button", { name: "修改邮箱", exact: true }).click();
  await expect(member.getByRole("status")).toHaveText("邮箱已更新");
  await member.getByLabel("修改密码的当前密码").fill(initial);
  await member
    .getByLabel("新密码", { exact: true })
    .fill("changed-password-123");
  await member.getByLabel("确认新密码").fill("changed-password-123");
  await member.getByRole("button", { name: "修改密码", exact: true }).click();
  await expect(
    member.getByRole("heading", { name: "登录测试平台" }),
  ).toBeVisible();
  await login(member, username, "changed-password-123");
  await expect(
    member.getByRole("heading", { name: "机器资源", exact: true }),
  ).toBeVisible();
  // Refresh the management revision after the member updated their own profile.
  await page.reload();
  await nav(page, "用户管理");
  await expect(row).toContainText("changed@example.com");
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "禁用", exact: true }).click();
  await expect(row).toContainText("已禁用");
  await member.reload();
  await expect(
    member.getByRole("heading", { name: "登录测试平台" }),
  ).toBeVisible();
  await login(member, username, "changed-password-123");
  await expect(member.getByRole("alert")).toContainText("账号或密码错误");
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "启用", exact: true }).click();
  await expect(row).toContainText("已启用");
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "重置密码" }).click();
  await expect(page.getByRole("status")).toContainText("123456");
  await login(member, username, "123456");
  await expect(
    member.getByRole("heading", { name: "机器资源", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/users-management.png",
    fullPage: true,
  });
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "删除", exact: true }).click();
  await expect(row).toHaveCount(0);
  await member.reload();
  await expect(
    member.getByRole("heading", { name: "登录测试平台" }),
  ).toBeVisible();
  await memberContext.close();
});
