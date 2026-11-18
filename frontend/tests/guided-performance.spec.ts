import { expect, test } from "@playwright/test";
test.use({ serviceWorkers: "block" });

test("performance guide previews mixed timed and MLPerf tools and opens only the confirmed task", async ({ page, context, baseURL }) => {
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
      body = { total_bytes: 3295001632, scene_count: 3, tests: payload.tests.map((spec: any, i: number) => ({
        id: `scene-${i}`, tool: spec.tool, command: spec.tool === "mlperf" ? "dtt -t mlperf -s benchmark" : `dtt ${spec.tool} --runtime-seconds ${spec.runtime_seconds}`,
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
  await page.getByLabel("MLPerf Storage").check();
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByLabel("任务名称").fill("向导测试");
  await page.getByLabel("fio / elbencho 测量时长").fill("2");
  await page.getByLabel("时长单位").selectOption("minutes");
  await page.getByLabel("训练模型").selectOption("resnet50");
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
    .toEqual([["fio", 120, "1073741824"], ["elbencho", 120, "1073741824"], ["mlperf", undefined, "1073741824"]]);
  expect(submissions[0].tests[2]).toEqual({ tool: "mlperf", mlperf_model: "resnet50", mlperf_epochs: 5,
    mlperf_accelerators: 1, concurrency: 4, total_size: "1073741824", rounds: 1 });
  expect(unexpected).toEqual([]);
});

test("MLPerf-only hides timed I/O controls and previews training settings", async ({ page, context, baseURL }) => {
  const unexpected: string[] = [];
  const previews: any[] = [];
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== baseURL) { unexpected.push(url.href); await route.abort(); return; }
    if (!url.pathname.startsWith("/api/")) { await route.continue(); return; }
    const path = url.pathname.replace("/api/v1", "");
    let body: unknown;
    if (path === "/auth/me") body = { id: "u1", username: "tester", email: "test@example.com", role: "admin", csrf_token: "local-only" };
    else if (path === "/performance/options") body = { machines: [{ id: "m1", name: "测试机", address: "192.0.2.9", ssh_user: "tester", maintenance: false }], mounts: [] };
    else if (path === "/performance/preview") {
      const payload = route.request().postDataJSON(); previews.push(payload);
      body = { total_bytes: 9235839564, scene_count: 1, tests: [{ id: "scene-1", tool: "mlperf",
        command: "dtt -t mlperf -s benchmark --mlperf-model unet3d", parameters: { ...payload.tests[0], file_count: 63, file_size: "146600628", total_size: "9235839564" } }] };
    } else { unexpected.push(`${route.request().method()} ${path}`); await route.abort(); return; }
    await route.fulfill({ json: body });
  });
  await page.goto("/#/start/performance");
  await page.getByLabel("目标机器").selectOption("m1");
  await page.getByLabel("目标目录").fill("/data");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByLabel("MLPerf Storage").check();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByLabel("测量时长")).toHaveCount(0);
  await expect(page.getByLabel("读写模式")).toHaveCount(0);
  await page.getByLabel("训练模型").selectOption("unet3d");
  await page.getByLabel("模拟 H100 加速器数量").fill("3");
  await page.getByLabel("每轮训练 epochs").fill("7");
  await page.getByLabel("每种工具请求数据量").fill("1");
  await page.getByLabel("数据量单位").selectOption("MiB");
  await expect(page.getByText(/63 个完整文件/)).toBeVisible();
  await expect(page.getByText(/每个模拟加速器至少 3 个完整 batch/)).toBeVisible();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByText("MLPerf 预计数据量")).toBeVisible();
  await page.getByRole("button", { name: "生成预览" }).click();
  await expect(page.getByText("dtt -t mlperf -s benchmark --mlperf-model unet3d")).toBeVisible();
  await page.screenshot({ path: "/tmp/dingofs-guided-mlperf-confirm.png", fullPage: true });
  expect(previews).toHaveLength(1);
  expect(previews[0].tests).toEqual([{ tool: "mlperf", mlperf_model: "unet3d", mlperf_epochs: 7,
    mlperf_accelerators: 3, concurrency: 4, total_size: "1048576", rounds: 1 }]);
  expect(unexpected).toEqual([]);
});
