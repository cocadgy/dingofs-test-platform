import { test, expect } from "@playwright/test";
test.use({ serviceWorkers: "block" });

const digest = "a".repeat(64);
const cluster = { id: "c1", name: "本地测试集群", mds_addresses: ["node.test:6900"], available: true,
  management_machine: { id: "m1", name: "控制机", address: "192.0.2.1", ssh_user: "test" } };
const profiles = ["env_one", "env_two"].map((name, index) => ({
  id: `e${index + 1}`, name, revision: 1, enabled: true, source_kind: "predefined", cluster_id: null,
  validation: "source_only", source_file: `conf/env/${name}.yaml`,
  display: { descriptor: { env_name: name, source_manifest: {}, digest, mds_addresses: ["node.test:6900"],
    targets: [{ role: "client", host: "node.test", user: "test", mutates: true }],
    client_count: 1, cache_count: 0, storage_type: "s3", programs: {}, directories: {}, modules: {}, issues: [] } },
}));

test("two environment guide requires preflight and confirmation then shows separate child reports", async ({ page, context, baseURL }) => {
  expect(baseURL).toBe("http://127.0.0.1:55173");
  const unexpected: string[] = [];
  const dialogs: string[] = [];
  page.on("dialog", async dialog => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  const installations: string[] = [];
  const submissions: Record<string, any>[] = [];
  let draftRevision = 0;
  let checks = 0;
  await context.routeWebSocket("**/*", route => {
    const url = new URL(route.url());
    if (url.hostname === "127.0.0.1" && url.port === "55173") route.connectToServer();
    else { unexpected.push(url.href); route.close(); }
  });
  const children = ["quota", "client"].map((module, index) => ({
    id: `child-${index}`, module, position: index, env_name: profiles[index].name,
    state: "success", stage: "completed", cases: [`${module}.yaml`], error: "",
    execution_targets: [{ machine_id: "m1", name: "控制机", ip: "192.0.2.1", user: "test" }],
    events: [{ seq: 1, time: "2026-11-10T00:00:00Z", stage: "execution", type: "case_finished", data: {} }],
    result: { case_counts: { total: 1, completed: 1, passed: 1, failed: 0, skipped: 0, known_bugs: 0 },
      case_results: [{ case_path: `${module}.yaml`, attempt: 1, status: "PASS" }], attempt_records: [],
      suite_errors: 0, cleanup_status: "cleaned", recovery_status: "not_required", retained_resources: [],
      report_status: "ready", report_path: "report/index.html", end_proof: true, may_continue: true },
  }));
  const run = { id: "local-parent", name: "双环境闭环", version: 2, can_manage: true, state: "success",
    phase: "已完成", snapshot: { cluster_name: cluster.name }, children, log: "", error: "" };
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== baseURL) { unexpected.push(url.href); await route.abort(); return; }
    if (!url.pathname.startsWith("/api/")) { await route.continue(); return; }
    const path = url.pathname.replace("/api/v1", "");
    const method = route.request().method();
    let body: any;
    if (path === "/auth/me") body = { id: "u1", username: "tester", email: "test@example.com", role: "admin", csrf_token: "local-only" };
    else if (path === "/functional/options") body = { digest, clusters: [cluster], modules: Object.fromEntries(
      ["quota", "client"].map(module => [module, [{ path: `${module}.yaml`, id: module, name: `${module} 本地用例`, run_level: "daily", sha256: digest }]])) };
    else if (path === "/functional/environments") body = profiles;
    else if (path.includes("/validate")) body = {};
    else if (path === "/functional/guided/metadata") body = { enabled: true, clusters: [cluster], machines: [{
      id: "m1", name: "控制机", address: "192.0.2.1", ssh_user: "test", aliases: ["node.test"], available: true }] };
    else if (path === "/functional/guided/compatibility") body = { modules: Object.fromEntries(
      route.request().postDataJSON().module_plans.map((plan: any) => [plan.module, { compatible: true, reasons: [],
        impacts: [], targets: [{ name: "控制机", address: "192.0.2.1", user: "test" }] }])) };
    else if (path.startsWith("/functional/drafts") && ["POST", "PUT"].includes(method)) body = {
      ...route.request().postDataJSON(), id: "draft-local", revision: ++draftRevision, state: "draft" };
    else if (path === "/functional/drafts") body = [];
    else if (path === "/functional/preflight") {
      checks++;
      body = { can_start: true, token: "local-token", expires_at: "2099-01-01T00:00:00Z",
        checks: [{ code: "runtime_version", ok: true }], impacts: [{ description: "只允许本地替身目标" }],
        required_confirmations: [digest] };
    } else if (path.includes("tool-jobs")) { installations.push(path); await route.abort(); return; }
    else if (path === "/functional/runs" && method === "POST") {
      submissions.push(route.request().postDataJSON()); body = run;
    } else if (path === "/functional/runs/local-parent") body = run;
    else if (/\/modules\/child-[01]\/report\/index.html$/.test(path)) {
      await route.fulfill({ contentType: "text/html; charset=utf-8", body: `<h1>${path.includes("child-0") ? "quota" : "client"} 独立报告</h1>` }); return;
    } else { unexpected.push(method + " " + path); await route.abort(); return; }
    await route.fulfill({ json: body });
  });
  await page.goto("/#/start/functional");
  await page.getByRole("combobox", { name: "测试环境", exact: true }).selectOption("e1");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  for (const module of ["quota", "client"]) await page.getByLabel(`选择 ${module} 全部用例`).check();
  await page.getByRole("combobox", { name: "client 测试环境", exact: true }).selectOption("e2");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await page.getByLabel("任务名称").fill("双环境闭环");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(page.getByRole("button", { name: "开始测试", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "检查环境", exact: true }).click();
  await expect(page.getByText("预检通过", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始测试", exact: true })).toBeDisabled();
  await page.getByLabel("我已阅读并确认以上影响范围").check();
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByRole("heading", { name: "双环境闭环", exact: true })).toBeVisible();
  expect(submissions).toHaveLength(1);
  expect(submissions[0].module_plans.map((plan: any) => [plan.module, plan.environment_profile_id]))
    .toEqual([["quota", "e1"], ["client", "e2"]]);
  expect(submissions[0].confirmed_impacts).toEqual([digest]);
  expect(checks).toBe(1);
  for (const [index, module] of ["quota", "client"].entries()) {
    await page.locator("details.functional-module > summary").nth(index).click();
    const link = page.locator("details.functional-module").nth(index).getByRole("link", { name: /Allure/ });
    await expect(link).toHaveAttribute("href", `/api/v1/functional/runs/local-parent/modules/child-${index}/report/index.html`);
    const popupPromise = context.waitForEvent("page");
    await link.click();
    const popup = await popupPromise;
    await expect(popup.getByRole("heading", { name: `${module} 独立报告` })).toBeVisible();
    await popup.close();
  }
  expect(installations).toEqual([]);
  expect(dialogs).toEqual([]);
  expect(unexpected).toEqual([]);
});
