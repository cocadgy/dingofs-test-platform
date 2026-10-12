import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRemoteSession, type RemoteController } from "./useRemoteSession";
import { RemoteSessionStatus } from "./RemoteSessionStatus";
import { LogPage } from "./LogPage";
import type { RemoteSession } from "./types";
const base: RemoteSession = {
  id: "r1",
  kind: "terminal",
  state: "ready",
  machine_id: "m1",
  machine_name: "node",
  address: "192.0.2.1",
  ssh_user: "ops",
  target_user: "ops",
  cluster_id: "c1",
  expires_at: "2030-01-01T00:00:00Z",
};
class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  readyState = 1;
  bufferedAmount = 0;
  sent: string[] = [];
  closed = false;
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  send(message: string) {
    this.sent.push(message);
  }
  close() {
    this.closed = true;
  }
  emit(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}
function response(value: unknown) {
  return new Response(JSON.stringify(value));
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  Socket.instances = [];
  window.history.replaceState(null, "", "/");
});

it("closes the stream and remote session on unmount with no reconnect or replay", async () => {
  const requests: { path: string; method?: string }[] = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      requests.push({ path, method: init?.method });
      return init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : response(base);
    }),
  );
  const { result, unmount } = renderHook(() => useRemoteSession());
  await act(async () => {
    await result.current.start({
      kind: "terminal",
      cluster_id: "c1",
      machine_id: "m1",
      confirmed: true,
    });
  });
  const ws = Socket.instances[0];
  expect(String(ws.url)).toBe(
    "ws://localhost:3000/api/v1/remote-sessions/r1/stream",
  );
  act(() => ws.onopen?.());
  act(() => result.current.send({ type: "input", data: "\u0003" }));
  expect(ws.sent).toEqual(['{"type":"input","data":"\\u0003"}']);
  unmount();
  expect(ws.closed).toBe(true);
  expect(
    requests.some(
      (row) =>
        row.method === "DELETE" && row.path === "/api/v1/remote-sessions/r1",
    ),
  ).toBe(true);
  expect(Socket.instances).toHaveLength(1);
});

it("closes a late create response after the user has already left", async () => {
  let resolve!: (value: Response) => void;
  const deleted: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        deleted.push(path);
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return new Promise<Response>((done) => {
        resolve = done;
      });
    }),
  );
  const { result, unmount } = renderHook(() => useRemoteSession());
  let task: Promise<void>;
  act(() => {
    task = result.current.start({
      kind: "files",
      cluster_id: "c1",
      service_id: "s1",
    });
  });
  unmount();
  await act(async () => {
    resolve(response({ ...base, kind: "files", state: "pending" }));
    await task;
  });
  expect(deleted).toEqual(["/api/v1/remote-sessions/r1"]);
});

it("clears an unsubmitted temporary password when a challenge changes", () => {
  const controller = {
    session: {
      ...base,
      state: "needs_password",
      challenge: "old",
      auth_account: "ops",
    },
    busy: false,
    authenticate: vi.fn(),
    close: vi.fn(),
  } as unknown as RemoteController;
  const { rerender } = render(<RemoteSessionStatus remote={controller} />);
  fireEvent.change(screen.getByLabelText("临时认证密码"), {
    target: { value: "secret-only-once" },
  });
  rerender(
    <RemoteSessionStatus
      remote={{
        ...controller,
        session: { ...base, state: "needs_password", challenge: "new" },
      }}
    />,
  );
  expect(screen.getByLabelText("临时认证密码")).toHaveValue("");
});

it("pauses log streaming, resumes from its cursor, and never reconnects after a drop", async () => {
  const creates: any[] = [];
  const deleted: string[] = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        deleted.push(path);
        return new Response(null, { status: 204 });
      }
      if (path.endsWith("/remote-targets"))
        return response({
          items: [
            {
              machine_id: "m1",
              name: "node",
              address: "192.0.2.1",
              ssh_user: "ops",
            },
          ],
          services: [
            {
              id: "s1",
              role: "mds",
              host: "node",
              log_dir: "/logs",
              machine_id: "m1",
              can_read_logs: true,
              match_state: "matched",
            },
          ],
        });
      if (path === "/api/v1/clusters/c1")
        return response({ name: "test", os_user: "dingo" });
      const body = JSON.parse(String(init?.body));
      creates.push(body);
      return response({
        ...base,
        id: `r${creates.length}`,
        kind: body.kind,
        state: body.kind === "log-follow" ? "ready" : "succeeded",
        result:
          body.kind === "files"
            ? {
                files: [
                  { file_id: "f1", name: "server.log", size: 12, mtime: 1 },
                ],
              }
            : { text: "before\n", cursor: { device: 1, inode: 2, offset: 7 } },
      });
    }),
  );
  render(<LogPage clusterId="c1" serviceId="s1" fileName="server.log" />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "实时追踪" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "实时追踪" }));
  await waitFor(() => expect(Socket.instances).toHaveLength(1));
  act(() => {
    Socket.instances[0].onopen?.();
    Socket.instances[0].emit({
      type: "text",
      text: "after\n",
      cursor: { device: 1, inode: 3, offset: 6 },
      reset: true,
    });
  });
  expect(screen.getByLabelText("日志内容").textContent).toBe("before\nafter\n");
  expect(screen.getByText(/日志发生轮转或截断/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "暂停追踪" }));
  expect(Socket.instances[0].closed).toBe(true);
  expect(deleted).toContain("/api/v1/remote-sessions/r3");
  expect(deleted).not.toContain("/api/v1/remote-sessions/r1");
  fireEvent.click(screen.getByRole("button", { name: "实时追踪" }));
  await waitFor(() => expect(Socket.instances).toHaveLength(2));
  expect(creates[3]).toMatchObject({
    kind: "log-follow",
    file_id: "f1",
    cursor: { device: 1, inode: 3, offset: 6 },
  });
  act(() => Socket.instances[1].onclose?.());
  expect(screen.getByRole("alert")).toHaveTextContent(/不会自动重连/);
  expect(Socket.instances).toHaveLength(2);
  expect(screen.getByLabelText("日志内容").textContent).toBe("before\nafter\n");
});
