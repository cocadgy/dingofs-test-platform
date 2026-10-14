let csrf = "";
let accountId = "";
export const setCsrf = (value: string, userId = "") => {
  csrf = value;
  accountId = userId;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  options: { keepalive?: boolean } = {},
): Promise<T> {
  const expectedUserId = accountId;
  const encodedBody = body === undefined ? undefined : JSON.stringify(body);
  const send = (token: string) =>
    fetch("/api/v1" + path, {
      method,
      ...options,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      ...(encodedBody === undefined ? {} : { body: encodedBody }),
    });
  let response = await send(csrf);
  let problem: { code?: string; message?: string } | undefined;
  if (!response.ok) {
    try {
      problem = await response.json();
    } catch {
      /* no raw proxy response */
    }
  }
  // A CSRF rejection happens before the endpoint creates a task. Another tab
  // may have replaced the shared session cookie while this page stayed open.
  if (
    response.status === 403 &&
    problem?.code === "csrf_failed" &&
    method !== "GET" &&
    path !== "/auth/login"
  ) {
    const current = await api<{ id: string; csrf_token: string }>("/auth/me");
    if (
      !expectedUserId ||
      current.id !== expectedUserId ||
      accountId !== expectedUserId
    ) {
      window.dispatchEvent(new Event("session-expired"));
      throw new ApiError(403, "登录账号已变化，请重新登录后再操作");
    }
    setCsrf(current.csrf_token, current.id);
    response = await send(csrf);
    problem = undefined;
    if (!response.ok) {
      try {
        problem = await response.json();
      } catch {
        /* no raw proxy response */
      }
    }
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login")
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, problem?.message || "请求失败，请稍后重试");
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
