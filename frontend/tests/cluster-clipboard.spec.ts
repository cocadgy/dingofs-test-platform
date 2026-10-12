import { test, expect } from "@playwright/test";

test("HTTP cluster log path copies to the actual clipboard without the Clipboard API", async ({
  page,
  context,
  baseURL,
}) => {
  const sessionRequests: string[] = [];
  const unexpectedRequests: string[] = [];
  const errors: string[] = [];
  context.on("page", (tab) =>
    tab.on("pageerror", (error) => errors.push(error.message)),
  );
  page.on("pageerror", (error) => errors.push(error.message));
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
        json: {
          id: "c1",
          name: "终端测试集群",
          external_name: "main-dingofs",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
          node_links: {},
          node_match_states: {},
          status_snapshot: {
            services: [
              {
                id: "mds1",
                role: "mds",
                host: "node-one",
                ports: [6900],
                state: "running",
                running_instances: 1,
                expected_instances: 1,
                status_text: "Up 1 day",
                log_dir: "/home/operator/dingofs/logs/mds0",
                data_dir: "/srv/dingofs/data",
                raft_dir: "/srv/dingofs/raft",
              },
            ],
          },
        },
      });
    if (path.endsWith("/remote-targets"))
      return route.fulfill({
        json: {
          items: ["m1", "m2"].map((id, index) => ({
            machine_id: id,
            name: `node-${index + 1}`,
            address: `192.0.2.${index + 1}`,
            ssh_port: 22,
            ssh_user: "operator",
            service_ids: [],
            can_read_logs: true,
          })),
          services: [],
        },
      });
    if (path.endsWith("/refresh-status"))
      return route.fulfill({
        json: {
          id: "status1",
          kind: "status",
          state: "succeeded",
          result: {},
        },
      });
    if (path.endsWith("/topology"))
      return route.fulfill({
        json: {
          id: "topology1",
          kind: "topology",
          state: "succeeded",
          result: { stdout: "global:\n  user: operator" },
        },
      });
    if (path.includes("/remote-sessions")) sessionRequests.push(path);
    unexpectedRequests.push(path);
    return route.fulfill({
      status: 500,
      json: { detail: "Unexpected mock endpoint" },
    });
  });
  // Fulfil an untrusted HTTP origin using the local preview assets. This
  // exercises browser security rules without depending on DNS or a real host.
  await context.route("http://clipboard.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith("/api/")) return route.fallback();
    const response = await route.fetch({
      url: new URL(url.pathname + url.search, baseURL).href,
    });
    return route.fulfill({ response });
  });
  await page.goto("http://clipboard.test/#/clusters/c1");
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
  expect(await page.evaluate(() => typeof navigator.clipboard)).toBe(
    "undefined",
  );
  await page.getByText("查看目录", { exact: true }).click();
  const directory = page
    .locator(".cluster-directory")
    .filter({ has: page.getByText("日志目录", { exact: true }) });
  await directory
    .getByRole("button", { name: "复制路径", exact: true })
    .click();
  await expect(directory.getByRole("status")).toHaveText("已复制");
  await expect(page.locator(".clipboard-copy-buffer")).toHaveCount(0);
  // Reading is permitted only on a secure origin. Read back the same browser's
  // real clipboard from localhost; the copy itself runs on insecure HTTP.
  const reader = await context.newPage();
  await context.grantPermissions(["clipboard-read"], {
    origin: "http://localhost",
  });
  await reader.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><title>Clipboard verification</title>",
    }),
  );
  await reader.goto("http://localhost/");
  expect(await reader.evaluate(() => navigator.clipboard.readText())).toBe(
    "/home/operator/dingofs/logs/mds0",
  );
  await reader.close();
  expect(sessionRequests).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
  expect(errors).toEqual([]);
});
