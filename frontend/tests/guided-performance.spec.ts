import { expect, test } from "@playwright/test";
test.use({ serviceWorkers: "block" });

test("performance guide previews two timed tools and opens only the confirmed task", async ({ page, context, baseURL }) => {
  const unexpected: string[] = [];
  const submissions: Record<string, any>[] = [];
  const previews: Record<string, any>[] = [];
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== baseURL) { unexpected.push(url.href); await route.abort(); return; }
    if (!url.pathname.startsWith("/api/")) { await route.continue(); return; }
    const path = url.pathname.replace("/api/v1", "");
    const method = route.request().method();
    let body: unknown;
    if (path === "/auth/me") body = { id: "u1", username: "tester", email: "test@example.com", role: "admin", csrf_token: "local-only" };
    else if (path === "/functional/guided/metadata") body = { enabled: false };
    else if (path === "/performance/options") body = { machines: [
      { id: "m1", name: "测试机", address: "192.0.2.9", ssh_user: "tester", maintenance: false },
    ], mounts: [{ id: "mount1", name: "测试挂载", state: "mounted", machine_id: "m1", path: "/mnt/test" }] };
    else if (path === "/performance/preview" && method === "POST") {
      const payload = route.request().postDataJSON(); previews.push(payload);
      body = { total_bytes: 2147483648, scene_count: 2, tests: payload.tests.map((spec: any, i: number) => ({
        id: `scene-${i}`, tool: spec.tool, command: `dtt ${spec.tool} --runtime-seconds ${spec.runtime_seconds}`,
        parameters: { ...spec, file_count: 4, file_size: "268435456" },
      })) };
    } else if (path === "/performance/runs" && method === "POST") {
      submissions.push(route.request().postDataJSON()); body = { id: "timed-run", name: "向导测试", state: "queued", phase: "queued", progress: 0, error: "", reports: {},
        snapshot: { machine_name: "测试机", connection: ["192.0.2.9", 22, "tester"], target_path: "/mnt/test", target_kind: "mount", tests: [] } };
    } else if (path === "/performance/runs") body = [];
    else if (path === "/performance/runs/timed-run") body = { id: "timed-run", name: "向导测试", state: "queued", phase: "queued", progress: 0,
      error: "", reports: {}, can_manage: true, snapshot: { machine_name: "测试机", connection: ["192.0.2.9", 22, "tester"], target_path: "/mnt/test", target_kind: "mount", tests: [] } };
    else { unexpected.push(`${method} ${path}`); await route.abort(); return; }
    await route.fulfill({ json: body });
  });
  await page.goto("/#/start");
  await page.getByLabel("想做什么").selectOption("performance");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page).toHaveURL(/#\/start\/performance$/);
  await page.getByLabel("目标机器").selectOption("m1");
  await page.getByLabel("测试位置").selectOption("mount");
  await page.getByLabel("挂载目录").selectOption("/mnt/test");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByLabel("fio").check();
  await page.getByLabel("elbencho").check();
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByLabel("任务名称").fill("向导测试");
  await page.getByLabel("测量时长").fill("2");
  await page.getByLabel("时长单位").selectOption("minutes");
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByRole("button", { name: "开始测试" })).toBeDisabled();
  await page.getByRole("button", { name: "生成预览" }).click();
  await expect(page.getByText("dtt fio --runtime-seconds 120")).toBeVisible();
  await page.screenshot({ path: "/tmp/dingofs-guided-performance-confirm.png", fullPage: true });
  await page.getByRole("button", { name: "开始测试" }).click();
  await expect(page).toHaveURL(/#\/performance\/timed-run$/);
  expect(previews).toHaveLength(1);
  expect(submissions).toHaveLength(1);
  expect(submissions[0].tests.map((spec: any) => [spec.tool, spec.runtime_seconds, spec.total_size]))
    .toEqual([["fio", 120, "1073741824"], ["elbencho", 120, "1073741824"]]);
  expect(unexpected).toEqual([]);
});
