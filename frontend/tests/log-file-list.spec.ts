import { test, expect, type Page } from "@playwright/test";

test("detail columns sort locally and double click opens an independent authorized log tab", async ({
  page,
  context,
}) => {
  const special = "mds.INFO #1+中文.log";
  const files = [
    { name: special, size: 2048, mtime: 3 },
    { name: "mds2.log", size: 9, mtime: 1 },
    { name: "mds10.txt", size: 1048576, mtime: 2 },
  ];
  const requests: { page: Page; body: any }[] = [];
  const listings = new Map<string, Page>();
  const errors: string[] = [];
  context.on("page", (tab) =>
    tab.on("pageerror", (error) => errors.push(error.message)),
  );
  page.on("pageerror", (error) => errors.push(error.message));
  let sequence = 0;
  await context.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u1",
          username: "admin",
          email: "admin@example.test",
          role: "admin",
          csrf_token: "test",
        },
      });
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: { id: "c1", name: "每日集成测试集群", os_user: "operator" },
      });
    if (path.endsWith("/remote-targets"))
      return route.fulfill({
        json: {
          items: [
            {
              machine_id: "m1",
              name: "node-one",
              address: "192.0.2.1",
              ssh_user: "operator",
            },
          ],
          services: [
            {
              id: "s1",
              role: "mds",
              host: "node-one",
              machine_id: "m1",
              log_dir: "/logs",
              can_read_logs: true,
              match_state: "matched",
            },
          ],
        },
      });
    if (request.method() === "DELETE") {
      listings.delete(path.split("/").at(-1)!);
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/remote-sessions") && request.method() === "POST") {
      const body = request.postDataJSON();
      const owner = request.frame().page();
      requests.push({ page: owner, body });
      const id = `r${++sequence}`;
      let result;
      if (body.kind === "files") {
        listings.set(id, owner);
        result = {
          files: files.map((file, index) => ({
            ...file,
            file_id: `${id}:${index}`,
          })),
        };
      } else {
        const [listingId, index] = body.file_id.split(":");
        if (listings.get(listingId) !== owner)
          return route.fulfill({
            status: 403,
            json: { message: "stale or cross-tab file capability" },
          });
        result = {
          text: `contents: ${files[Number(index)].name}`,
          cursor: { device: 1, inode: 2, offset: 20 },
        };
      }
      return route.fulfill({
        json: {
          id,
          kind: body.kind,
          state: "succeeded",
          target_user: "operator",
          result,
        },
      });
    }
    return route.fulfill({
      status: 500,
      json: { message: `unexpected endpoint ${path}` },
    });
  });
  await page.goto("/#/clusters/c1/logs/s1");
  const table = page.getByRole("table", { name: "日志文件列表", exact: true });
  await expect(table.locator("tbody tr")).toHaveCount(3);
  for (const title of ["名称", "修改时间", "类型", "大小"])
    await expect(
      table.getByRole("columnheader", { name: title, exact: true }),
    ).toBeVisible();
  await expect(
    table.getByRole("columnheader", { name: "修改时间", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  await expect(table.locator("tbody td:first-child")).toHaveText([
    special,
    "mds10.txt",
    "mds2.log",
  ]);
  await table.getByRole("button", { name: "大小", exact: true }).click();
  await expect(table.locator("tbody td:first-child")).toHaveText([
    "mds2.log",
    special,
    "mds10.txt",
  ]);
  await table.getByRole("button", { name: "大小", exact: true }).click();
  await expect(table.locator("tbody td:first-child")).toHaveText([
    "mds10.txt",
    special,
    "mds2.log",
  ]);
  const row = table
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: special, exact: true }) });
  await row.click();
  expect(requests.map((row) => row.body.kind)).toEqual(["files"]);
  const popup = page.waitForEvent("popup");
  await row.dblclick();
  const reader = await popup;
  await expect(reader.getByLabel("日志内容", { exact: true })).toHaveText(
    `contents: ${special}`,
  );
  expect(new URLSearchParams(reader.url().split("?")[1]).get("file")).toBe(
    special,
  );
  expect(await reader.evaluate(() => window.opener === null)).toBe(true);
  await expect(page).toHaveURL(/#\/clusters\/c1\/logs\/s1$/);
  expect(
    requests.filter((row) => row.page === page).map((row) => row.body.kind),
  ).toEqual(["files"]);
  expect(
    requests.filter((row) => row.page === reader).map((row) => row.body.kind),
  ).toEqual(["files", "read"]);
  expect(requests.at(-1)!.body.file_id).toBe("r2:0");
  await expect(reader).toHaveTitle(`${special} · 每日集成测试集群 · 服务日志`);
  await page.screenshot({
    path: test.info().outputPath("log-file-details.png"),
    fullPage: true,
  });
  await reader.screenshot({
    path: test.info().outputPath("log-file-reader.png"),
    fullPage: true,
  });
  await page.close();
  await reader.getByLabel("末尾行数", { exact: true }).selectOption("1000");
  await expect(reader.getByLabel("日志内容", { exact: true })).toHaveText(
    `contents: ${special}`,
  );
  expect(requests.at(-1)!.body).toMatchObject({
    kind: "read",
    file_id: "r2:0",
    lines: 1000,
  });
  await reader.getByRole("button", { name: "重新查找文件", exact: true }).click();
  await expect(reader.getByLabel("日志内容", { exact: true })).toHaveText(`contents: ${special}`);
  expect(requests.at(-1)!.body).toMatchObject({kind:"read",file_id:"r5:0",lines:1000});
  await expect.poll(() => listings.has("r2")).toBe(false);
  expect(errors).toEqual([]);
});
