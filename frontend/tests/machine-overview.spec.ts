import { test, expect } from "@playwright/test";
test("full-width machine table, per-column filters, sort and detail history", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill("admin");
  await page.getByLabel("密码", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  const table = page.getByRole("table", { name: "机器资源列表" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveCount(10);
  await expect(table.getByRole("searchbox")).toHaveCount(10);
  await page.getByLabel("搜索资源名").fill("overview-");
  await expect(page.getByText(/筛选结果 45 台/)).toBeVisible();
  await page.screenshot({
    path: "test-results/machine-overview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(
    page.getByRole("button", { name: "overview-21", exact: true }),
  ).toBeVisible();
  await page.getByLabel("搜索资源名").fill("overview-45");
  await expect(
    page.getByRole("button", { name: "overview-45", exact: true }),
  ).toBeVisible();
  await page.getByLabel("搜索网卡速率（最大）").fill("25000");
  await expect(page.getByText(/筛选结果 1 台/)).toBeVisible();
  await page.getByLabel("搜索RDMA设备").fill("mlx5");
  await expect(page.getByText(/筛选结果 1 台/)).toBeVisible();
  await page.getByRole("button", { name: "按总内存排序" }).click();
  const row = table.getByRole("row").filter({ hasText: "overview-45" });
  await row.getByRole("cell").last().click();
  await expect(
    page.getByRole("heading", { name: "机器资源详情", exact: true }),
  ).toBeVisible();
  await expect(table).toHaveCount(0);
  await expect(page).toHaveURL(/#\/machines\/[0-9a-f-]+$/);
  await expect(
    page.getByRole("heading", { name: "overview-45", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "overview-45", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(table).toBeVisible();
  // Refresh reconstructed the page state; check retention again without a reload.
  await page.getByLabel("搜索资源名").fill("overview-");
  await page.getByLabel("搜索CPU型号").fill("EPYC");
  await page.getByRole("button", { name: "按总内存排序" }).click();
  await page.getByRole("button", { name: "下一页" }).click();
  const chosen = table.locator("tbody tr").first();
  const name = await chosen.getByRole("button").innerText();
  await chosen.getByRole("button").click();
  await page.getByRole("button", { name: "返回机器概览" }).click();
  await expect(page.getByLabel("搜索CPU型号")).toHaveValue("EPYC");
  await expect(page.getByText("第 2 / 3 页")).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: /总内存/ }),
  ).toHaveAttribute("aria-sort", "ascending");
  await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
});
