import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
const csp = readFileSync(
  new URL("../../deploy/nginx.conf", import.meta.url),
  "utf8",
).match(/Content-Security-Policy "([^"]+)"/)![1];
async function fixtures(
  page: Page,
  options: { mockClipboard?: boolean; terminalText?: string } = {},
) {
  const creates: any[] = [];
  const removed: string[] = [];
  const messages: any[] = [];
  const errors: string[] = [];
  const violations: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      /Content Security Policy|Refused to|violates.*directive/.test(msg.text())
    )
      violations.push(msg.text());
  });
  if (options.mockClipboard !== false)
    await page.addInitScript(() => {
      (window as any).__clipboardWrites = [];
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: async (text: string) => {
            (window as any).__clipboardWrites.push(text);
          },
          readText: async () => "echo pasted",
        },
      });
    });
  await page.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith("/api/")) {
      if (path === "/api/v1/auth/me")
        return route.fulfill({
          json: {
            id: "u1",
            username: "admin",
            email: "admin@example.test",
            role: "admin",
            csrf_token: "csrf",
          },
        });
      if (path === "/api/v1/clusters/c1")
        return route.fulfill({
          json: { name: "DingoFS 验收集群", os_user: "dingo" },
        });
      if (path.endsWith("/remote-targets"))
        return route.fulfill({
          json: {
            items: [
              {
                machine_id: "m1",
                name: "node-one",
                address: "192.0.2.1",
                ssh_port: 2222,
                ssh_user: "operator",
                service_ids: ["s1"],
                can_read_logs: true,
              },
            ],
            services: [
              {
                id: "s1",
                role: "mds",
                host: "node-one",
                log_dir: "/var/log/dingofs",
                machine_id: "m1",
                can_read_logs: true,
                match_state: "matched",
              },
            ],
          },
        });
      if (route.request().method() === "DELETE") {
        removed.push(path);
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/v1/remote-sessions") {
        const body = route.request().postDataJSON();
        creates.push(body);
        const id = `r${creates.length}`;
        return route.fulfill({
          status: 202,
          json: {
            id,
            kind: body.kind,
            state: ["log-follow", "terminal"].includes(body.kind)
              ? "ready"
              : "succeeded",
            machine_id: "m1",
            machine_name: "node-one",
            address: "192.0.2.1",
            ssh_port: 2222,
            ssh_user: "operator",
            target_user: body.kind === "terminal" ? "operator" : "dingo",
            cluster_id: "c1",
            service_id: "s1",
            log_dir: "/var/log/dingofs",
            expires_at: "2030-01-01T00:00:00Z",
            result:
              body.kind === "files"
                ? {
                    files: [
                      {
                        file_id: "r1:0",
                        name: "mds.INFO.log",
                        size: 2048,
                        mtime: 1770000000,
                      },
                      {
                        file_id: "r1:1",
                        name: "oversized.log",
                        size: 150 * 1024 * 1024,
                        mtime: 1,
                      },
                    ],
                    truncated: false,
                  }
                : {
                    text: "2026-09-24 10:00:00 INFO mds ready\n<script>alert(1)</script>\nerror[1] literal match\nerror1 different line\n",
                    cursor: { device: 1, inode: 2, offset: 120 },
                  },
          },
        });
      }
      return route.fulfill({
        status: 500,
        json: { message: "Unexpected fixture route" },
      });
    }
    if (route.request().resourceType() === "document") {
      const original = await route.fetch();
      return route.fulfill({
        response: original,
        headers: { ...original.headers(), "content-security-policy": csp },
      });
    }
    return route.continue();
  });
  await page.routeWebSocket("**/remote-sessions/*/stream", (ws) => {
    ws.send(
      JSON.stringify({
        type: "text",
        text: page.url().includes("/terminal/")
          ? (options.terminalText ??
            "\u001b[32moperator@node-one\u001b[0m:~$ \r\n\u001b]52;c;cmVtb3RlLW92ZXJ3cml0ZQ==\u0007\u001b]8;;https://example.invalid/\u0007inert-link\u001b]8;;\u0007\r\n")
          : "2026-09-24 10:00:01 INFO heartbeat\n",
        cursor: { device: 1, inode: 2, offset: 158 },
      }),
    );
    ws.onMessage((message) => messages.push(JSON.parse(String(message))));
  });
  return { creates, removed, messages, errors, violations };
}

test("logs use literal text, keep file authorization, resume cursors and download loaded content", async ({
  page,
}, info) => {
  const state = await fixtures(page);
  await page.goto("/#/clusters/c1/logs/s1?file=mds.INFO.log");
  await expect(page.getByLabel("日志内容")).toContainText(
    "<script>alert(1)</script>",
  );
  expect(state.removed).not.toContain("/api/v1/remote-sessions/r1");
  await page.getByLabel("过滤当前内容").fill("error[1]");
  await expect(page.getByLabel("日志内容")).toHaveText(
    "error[1] literal match",
  );
  await page.getByLabel("过滤当前内容").clear();
  await page.getByRole("button", { name: "实时追踪" }).click();
  await expect(page.getByLabel("日志内容")).toContainText("heartbeat");
  await page.getByRole("button", { name: "暂停追踪" }).click();
  await page.getByRole("button", { name: "实时追踪" }).click();
  await expect
    .poll(() => state.creates.filter((row) => row.kind === "log-follow").length)
    .toBe(2);
  expect(state.creates.at(-1).cursor).toEqual({
    device: 1,
    inode: 2,
    offset: 158,
  });
  await page.getByRole("button", { name: "暂停追踪" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载当前内容" }).click();
  expect((await download).suggestedFilename()).toBe("mds.INFO.log.loaded.txt");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath("logs.png"), fullPage: true });
  await page.goto("/#/clusters/c1/logs/s1?file=oversized.log");
  await expect(
    page.getByRole("button", { name: "下载远程文件" }),
  ).toBeDisabled();
  expect(state.errors).toEqual([]);
  expect(state.violations).toEqual([]);
});

test("real xterm supports confirmed input, Ctrl+C, resize and paste with strict deployment CSP", async ({
  page,
}, info) => {
  const state = await fixtures(page);
  await page.goto("/#/clusters/c1/terminal/m1");
  await expect(page.getByRole("button", { name: "连接终端" })).toBeEnabled();
  expect(state.creates).toEqual([]);
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("192.0.2.1:2222");
    expect(dialog.message()).toContain("operator");
    void dialog.dismiss();
  });
  await page.getByRole("button", { name: "连接终端" }).click();
  expect(state.creates).toEqual([]);
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "连接终端" }).click();
  await expect(page.locator(".xterm-screen")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("operator@node-one");
  expect(state.creates[0]).toMatchObject({
    kind: "terminal",
    cluster_id: "c1",
    machine_id: "m1",
    confirmed: true,
  });
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("pwd");
  await page.keyboard.press("Control+c");
  await expect
    .poll(() =>
      state.messages
        .filter((row) => row.type === "input")
        .map((row) => row.data)
        .join(""),
    )
    .toBe("pwd\u0003");
  await page.getByRole("button", { name: "粘贴", exact: true }).click();
  await expect
    .poll(() =>
      state.messages
        .filter((row) => row.type === "input")
        .map((row) => row.data)
        .join(""),
    )
    .toContain("echo pasted");
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect
    .poll(() => state.messages.filter((row) => row.type === "resize").length)
    .toBeGreaterThan(0);
  expect(await page.evaluate(() => (window as any).__clipboardWrites)).toEqual(
    [],
  );
  await expect(
    page
      .locator(".xterm-rows")
      .getByText("operator@node-one", { exact: false }),
  ).toBeVisible();
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: info.outputPath("terminal.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "断开连接", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新连接" })).toBeEnabled();
  expect(state.creates).toHaveLength(1);
  expect(state.errors).toEqual([]);
  expect(state.violations).toEqual([]);
  await expect
    .poll(() => page.evaluate(() => document.adoptedStyleSheets.length))
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: /个人设置/ }).click();
  await expect
    .poll(() => page.evaluate(() => document.adoptedStyleSheets.length))
    .toBe(0);
});

test("HTTP terminal selection copies real text through fallback without sending input", async ({
  page,
  context,
  baseURL,
}) => {
  const selectedText = "COPY_THIS_TERMINAL_TEXT";
  const state = await fixtures(page, {
    mockClipboard: false,
    terminalText: selectedText + "\r\n",
  });
  await page.route("http://terminal-clipboard.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith("/api/")) return route.fallback();
    const response = await route.fetch({
      url: new URL(url.pathname + url.search, baseURL).href,
    });
    return route.fulfill({
      response,
      headers: { ...response.headers(), "content-security-policy": csp },
    });
  });
  await page.goto("http://terminal-clipboard.test/#/clusters/c1/terminal/m1");
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
  expect(await page.evaluate(() => typeof navigator.clipboard)).toBe(
    "undefined",
  );
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "连接终端", exact: true }).click();
  const output = page
    .locator(".xterm-rows")
    .getByText(selectedText, { exact: true });
  await expect(output).toBeVisible();
  const copyButton = page.getByRole("button", {
    name: "复制选中内容",
    exact: true,
  });
  await copyButton.click();
  await expect(
    page.getByText("请先选中终端文字", { exact: true }),
  ).toBeVisible();
  await output.dblclick();
  await expect(output).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await copyButton.click();
  await expect(page.getByText("已复制选中文本", { exact: true })).toBeVisible();
  // Clicking the toolbar must keep the xterm selection available for reuse.
  await copyButton.click();
  await expect(page.getByText("已复制选中文本", { exact: true })).toBeVisible();
  await expect(page.locator(".clipboard-copy-buffer")).toHaveCount(0);
  // The write uses insecure HTTP. Read the real browser clipboard back from
  // localhost, where Clipboard API reads are allowed.
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
    selectedText,
  );
  await reader.close();
  expect(state.messages.filter((row) => row.type === "input")).toEqual([]);
  await page.getByRole("button", { name: "粘贴", exact: true }).click();
  const draft = page.getByRole("textbox", { name: "粘贴内容", exact: true });
  await expect(draft).toBeFocused();
  await expect(
    page.getByRole("button", { name: "发送到终端", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Control+v");
  await expect(draft).toHaveValue(selectedText);
  expect(state.messages.filter((row) => row.type === "input")).toEqual([]);
  await page.getByRole("button", { name: "取消粘贴", exact: true }).click();
  await expect(draft).toHaveCount(0);
  expect(state.messages.filter((row) => row.type === "input")).toEqual([]);
  await page.getByRole("button", { name: "粘贴", exact: true }).click();
  await expect(draft).toHaveValue("");
  await page.keyboard.press("Control+v");
  await page.getByRole("button", { name: "发送到终端", exact: true }).click();
  await expect(draft).toHaveCount(0);
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("pwd");
  await expect
    .poll(() =>
      state.messages
        .filter((row) => row.type === "input")
        .map((row) => row.data)
        .join(""),
    )
    .toBe(selectedText + "pwd");
  expect(state.errors).toEqual([]);
  expect(state.violations).toEqual([]);
});
