import { test, expect } from "@playwright/test";
test("first trust, changed key acknowledgement and persistent trust", async ({
  page,
}) => {
  const name = "trust-" + Date.now();
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill("admin");
  await page.getByLabel("密码", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "登记机器资源" }).click();
  await page.getByLabel("名称", { exact: true }).fill(name);
  await page.getByLabel("主机地址", { exact: true }).fill(name + ".test");
  await page.getByLabel("SSH 用户", { exact: true }).fill("root");
  await page.getByLabel("SSH 密码（留空保留原密码）").fill("local-test-only");
  await page.getByRole("button", { name: "保存资源" }).click();
  await page.getByRole("button", { name: "更新机器信息" }).click();
  const panel = page.getByRole("region", { name: "SSH 主机身份确认" });
  await expect(panel).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "信任并继续" }),
  ).toBeDisabled();
  await expect(panel).toContainText(name + ".test:22");
  await expect(panel).toContainText("SHA256:");
  await page.screenshot({
    path: "test-results/host-trust-first.png",
    fullPage: true,
  });
  await panel.getByLabel("我已通过可信渠道核对该机器的 SSH 指纹").check();
  await panel.getByRole("button", { name: "信任并继续" }).click();
  await expect(page.getByText("CPU Model", { exact: true })).toBeVisible();
  await expect(panel).toHaveCount(0);
  await page.getByRole("button", { name: "更新机器信息" }).click();
  await expect(
    panel.getByRole("heading", { name: "SSH 主机密钥已变化" }),
  ).toBeVisible();
  await expect(panel).toContainText("原指纹");
  await expect(panel).toContainText("新指纹");
  await expect(
    panel.getByRole("button", { name: "信任新密钥并继续" }),
  ).toBeDisabled();
  await expect(page.getByText("CPU Model", { exact: true })).toBeVisible();
  await panel.getByLabel("我已通过可信渠道核对该机器的 SSH 指纹").check();
  await panel.getByRole("button", { name: "信任新密钥并继续" }).click();
  await expect(panel).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "机器资源详情", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "更新机器信息" }).click();
  await expect(page.getByRole("status")).toContainText("采集成功");
  await expect(panel).toHaveCount(0);
});
