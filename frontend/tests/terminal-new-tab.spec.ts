import { test, expect } from "@playwright/test";

test("cluster terminal opens the selected machine in a new tab and keeps the cluster draft", async ({ page, context }) => {
  const sessionRequests: string[] = [];
  const unexpectedRequests: string[] = [];
  const errors: string[] = [];
  context.on("page", (tab) => tab.on("pageerror", (error) => errors.push(error.message)));
  page.on("pageerror", (error) => errors.push(error.message));
  await context.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: {
      id: "u1", username: "admin", email: "admin@example.test", role: "admin", csrf_token: "test",
    } });
    if (path.endsWith("/clusters/c1")) return route.fulfill({ json: {
      id: "c1", name: "终端测试集群", external_name: "main-dingofs", creator_id: "u1",
      revision: 1, archived: false, binding_state: "verified", node_links: {}, node_match_states: {},
    } });
    if (path.endsWith("/remote-targets")) return route.fulfill({ json: {
      items: ["m1", "m2"].map((id, index) => ({
        machine_id: id, name: `node-${index + 1}`, address: `192.0.2.${index + 1}`,
        ssh_port: 22, ssh_user: "operator", service_ids: [], can_read_logs: true,
      })), services: [],
    } });
    if (path.endsWith("/refresh-status")) return route.fulfill({ json: {
      id: "status1", kind: "status", state: "succeeded", result: {},
    } });
    if (path.endsWith("/topology")) return route.fulfill({ json: {
      id: "topology1", kind: "topology", state: "succeeded", result: { stdout: "global:\n  user: operator" },
    } });
    if (path.includes("/remote-sessions")) sessionRequests.push(path);
    unexpectedRequests.push(path);
    return route.fulfill({ status: 500, json: { detail: "Unexpected mock endpoint" } });
  });
  await page.goto("/#/clusters/c1");
  await page.getByRole("combobox", { name: "终端目标", exact: true }).selectOption("m2");
  await page.getByRole("button", { name: "编辑登记信息", exact: true }).click();
  await page.getByLabel("别名", { exact: true }).fill("未保存的集群别名");
  const originalUrl = page.url();
  const opened = page.waitForEvent("popup");
  await page.getByRole("link", { name: /打开终端/ }).click();
  const terminal = await opened;
  await expect(terminal).toHaveURL(/#\/clusters\/c1\/terminal\/m2$/);
  await expect(terminal.getByRole("heading", { name: "终端测试集群 · 管理员终端" })).toBeVisible();
  await expect(terminal.getByRole("button", { name: "连接终端", exact: true })).toBeEnabled();
  expect(await terminal.evaluate(() => window.opener === null)).toBe(true);
  await expect(page).toHaveURL(originalUrl);
  await expect(page.getByLabel("别名", { exact: true })).toHaveValue("未保存的集群别名");
  expect(sessionRequests).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
  expect(errors).toEqual([]);
  await terminal.close();
  await expect(page.getByLabel("别名", { exact: true })).toHaveValue("未保存的集群别名");
});
