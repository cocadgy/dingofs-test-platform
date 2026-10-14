import { afterEach, expect, test, vi } from "vitest";
import { api, setCsrf } from "./client";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  setCsrf("");
  vi.unstubAllGlobals();
});

test("refreshes a stale CSRF token and retries the same resource request once", async () => {
  setCsrf("old-token", "user-1");
  const calls: Array<{ path: string; init: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    calls.push({ path, init });
    if (path.endsWith("/auth/me")) return json({ id: "user-1", csrf_token: "new-token" });
    return calls.filter((call) => call.path.endsWith("/resource-operations")).length === 1
      ? json({ code: "csrf_failed", message: "请求验证失败，请刷新页面" }, 403)
      : json({ id: "operation-1" }, 202);
  }));
  const body = { request_id: "same-request-id", action: "fs.list" };
  expect(await api("/clusters/c1/resource-operations", "POST", body)).toEqual({ id: "operation-1" });
  expect(calls.map((call) => call.path)).toEqual([
    "/api/v1/clusters/c1/resource-operations",
    "/api/v1/auth/me",
    "/api/v1/clusters/c1/resource-operations",
  ]);
  expect(calls[0].init.body).toBe(calls[2].init.body);
  expect((calls[0].init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("old-token");
  expect((calls[2].init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("new-token");
});

test("does not retry a rejected request when the cookie belongs to another account", async () => {
  setCsrf("old-token", "user-1");
  const paths: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    paths.push(path);
    return path.endsWith("/auth/me")
      ? json({ id: "user-2", csrf_token: "user-2-token" })
      : json({ code: "csrf_failed", message: "请求验证失败，请刷新页面" }, 403);
  }));
  await expect(api("/clusters/c1/resource-operations", "POST", { request_id: "r1" }))
    .rejects.toThrow("账号已变化");
  expect(paths).toEqual(["/api/v1/clusters/c1/resource-operations", "/api/v1/auth/me"]);
});

test("does not retry unrelated 403 failures", async () => {
  setCsrf("token", "user-1");
  const fetch = vi.fn(async () => json({ code: "forbidden", message: "没有权限" }, 403));
  vi.stubGlobal("fetch", fetch);
  await expect(api("/clusters/c1/resource-operations", "POST", {})).rejects.toThrow("没有权限");
  expect(fetch).toHaveBeenCalledTimes(1);
});
