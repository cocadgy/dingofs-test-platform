import { test, expect } from "@playwright/test";

test("completed performance HTML renders inside its isolated frame", async ({
  page,
}) => {
  test.skip(
    !process.env.PLATFORM_PERFORMANCE_RUN_ID ||
      !process.env.PLATFORM_E2E_PASSWORD,
    "Requires a completed test run and explicit credentials",
  );
  await page.goto("/#/performance/" + process.env.PLATFORM_PERFORMANCE_RUN_ID);
  await page
    .getByLabel("用户名")
    .fill(process.env.PLATFORM_E2E_USER || "admin");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.PLATFORM_E2E_PASSWORD!);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("heading", { name: "测试报告", exact: true }).waitFor();
  if (
    await page.getByRole("button", { name: "查看报告", exact: true }).count()
  ) {
    await page
      .getByRole("button", { name: "查看报告", exact: true })
      .first()
      .click();
  }
  await page.getByRole("button", { name: "查看网页报告" }).first().click();
  await expect(page.locator("iframe")).toHaveAttribute(
    "sandbox",
    "allow-scripts",
  );
  await expect(
    page.frameLocator("iframe").getByText("平均总带宽", { exact: true }),
  ).toBeVisible();
});

test("matrix controls preview eight parameter combinations in deployed UI", async ({
  page,
}) => {
  test.skip(
    !process.env.PLATFORM_E2E_PASSWORD,
    "Requires explicit credentials",
  );
  await page.goto("/#/performance");
  await page
    .getByLabel("用户名")
    .fill(process.env.PLATFORM_E2E_USER || "admin");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.PLATFORM_E2E_PASSWORD!);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "新建测试" }).click();
  await page.getByRole("button", { name: "添加工具", exact: true }).click();
  const machine = page.getByLabel("目标机器");
  await expect(
    machine.locator("option").filter({ hasText: "172.30.14.128" }),
  ).toHaveCount(1);
  await machine.selectOption(
    (await machine
      .locator("option")
      .filter({ hasText: "172.30.14.128" })
      .getAttribute("value")) || "",
  );
  await page
    .getByLabel("目标目录", { exact: true })
    .fill("/tmp/matrix-ui-preview");
  async function selectValues(label: string, values: string[]) {
    const group = page.getByRole("group", { name: label, exact: true });
    while (await group.getByRole("button").count())
      await group.getByRole("button").first().click();
    for (const value of values) {
      const match = /^(\d+)([KMGTPE]?i?B)$/.exec(value);
      if (match)
        await page
          .getByLabel(label + "单位", { exact: true })
          .selectOption(match[2]);
      await page
        .getByLabel(label + "自定义值", { exact: true })
        .fill(match ? match[1] : value);
      await page
        .getByRole("button", {
          name: "添加 " + label + "自定义值",
          exact: true,
        })
        .click();
    }
  }
  await selectValues("并发作业数", ["2", "1"]);
  expect(
    await page
      .getByRole("list", { name: "并发作业数已选值" })
      .getByRole("listitem")
      .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-value"))),
  ).toEqual(["1", "2"]);
  await selectValues("每文件大小", ["1MiB"]);
  await selectValues("文件总数量", ["2"]);
  await selectValues("Block 大小", ["4KiB"]);
  await page.getByLabel("fio 顺序读", { exact: true }).check();
  await page.getByLabel("fio Direct I/O 关闭", { exact: true }).check();
  await page.getByRole("button", { name: "预览执行计划" }).click();
  await expect(page.getByText("共 8 个场景，按下表顺序执行。")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "确认并开始测试" }),
  ).toBeVisible();
  await expect(page.locator(".performance-preview tbody tr")).toHaveCount(8);
  await page
    .getByRole("button", { name: "删除 并发作业数 2", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "确认并开始测试" }),
  ).toHaveCount(0);
});
