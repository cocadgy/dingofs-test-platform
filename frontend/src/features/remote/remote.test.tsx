import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appendLog, filterLog } from "./logBuffer";
import { LogPage } from "./LogPage";
import { TerminalPage } from "./TerminalPage";
import { InventoryPage } from "../inventory/InventoryPage";

const target = {
  machine_id: "m1",
  name: "node-one",
  address: "192.0.2.1",
  ssh_port: 2222,
  ssh_user: "operator",
  service_ids: ["s1"],
  can_read_logs: true,
};
const service = {
  id: "s1",
  role: "mds",
  host: "node-one",
  log_dir: "/logs",
  machine_id: "m1",
  can_read_logs: true,
  match_state: "matched",
};
const cluster = { id: "c1", name: "test-cluster", os_user: "dingo" };
const session = {
  id: "r1",
  kind: "files",
  state: "succeeded",
  machine_id: "m1",
  machine_name: "node-one",
  address: "192.0.2.1",
  ssh_user: "operator",
  target_user: "dingo",
  cluster_id: "c1",
  service_id: "s1",
  log_dir: "/logs",
  expires_at: "2030-01-01T00:00:00Z",
};
function response(value: unknown) {
  return new Response(JSON.stringify(value));
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("bounded plain-text log content", () => {
  it("evicts oldest lines and marks loss while retaining the newest data", () => {
    const result = appendLog(
      { text: "first\nsecond\n", truncated: false },
      "third\nfourth",
      3,
    );
    expect(result.text).toBe("second\nthird\nfourth");
    expect(result.truncated).toBe(true);
  });
  it("bounds UTF-8 bytes without splitting multibyte characters", () => {
    const result = appendLog(
      { text: "", truncated: false },
      "前面🙂最后",
      5000,
      10,
    );
    expect(result.text).toBe("🙂最后");
    expect(new TextEncoder().encode(result.text).length).toBe(10);
    expect(result.truncated).toBe(true);
  });
  it("filters literal strings in the loaded buffer including regex punctuation", () => {
    expect(
      filterLog("good\nerror[1]\nerror1\n<script>x</script>", "error[1]"),
    ).toBe("error[1]");
    expect(filterLog("<script>x</script>", "")).toBe("<script>x</script>");
  });
});

it("requires an explicit terminal action and cancelled confirmation never creates a session", async () => {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") requests.push(path);
      return response(
        path.endsWith("remote-targets")
          ? { items: [target], services: [service] }
          : cluster,
      );
    }),
  );
  vi.stubGlobal(
    "confirm",
    vi.fn(() => false),
  );
  render(<TerminalPage clusterId="c1" machineId="m1" admin />);
  const button = await screen.findByRole("button", { name: "连接终端" });
  expect(requests).toEqual([]);
  fireEvent.click(button);
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("192.0.2.1:2222"),
  );
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("operator"),
  );
  expect(requests).toEqual([]);
});

it("denies a non-admin terminal without making a connection", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<TerminalPage clusterId="c1" machineId="m1" admin={false} />);
  expect(screen.getByText(/仅管理员/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "连接终端" })).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["missing", "ambiguous", "permission"])(
  "explains %s log access and never opens SSH",
  async (reason) => {
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "POST") posts.push(path);
        return response(
          path.endsWith("remote-targets")
            ? {
                items: [target],
                services: [
                  {
                    ...service,
                    can_read_logs: false,
                    match_state: reason === "permission" ? "matched" : reason,
                  },
                ],
              }
            : cluster,
        );
      }),
    );
    render(<LogPage clusterId="c1" serviceId="s1" />);
    await screen.findByText(
      reason === "missing"
        ? /未匹配机器资源/
        : reason === "ambiguous"
          ? /匹配冲突/
          : /创建者/,
    );
    expect(posts).toEqual([]);
  },
);

it("a file page lists before reading its opaque file id and renders HTML as text", async () => {
  const creates: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/remote-targets"))
        return response({ items: [target], services: [service] });
      if (path === "/api/v1/clusters/c1") return response(cluster);
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      const body = JSON.parse(String(init?.body));
      creates.push(body);
      return response({
        ...session,
        kind: body.kind,
        result:
          body.kind === "files"
            ? {
                files: [
                  { file_id: "opaque", name: "latest.log", size: 12, mtime: 1 },
                ],
                truncated: false,
              }
            : {
                text: "<script>alert(1)</script>\nerror[1]\nerror1",
                cursor: { device: 1, inode: 2, offset: 47 },
              },
      });
    }),
  );
  render(<LogPage clusterId="c1" serviceId="s1" fileName="latest.log" />);
  const output = await screen.findByLabelText("日志内容");
  await waitFor(() =>
    expect(output).toHaveTextContent("<script>alert(1)</script>"),
  );
  expect(output.querySelector("script")).toBeNull();
  expect(creates).toEqual([
    { kind: "files", cluster_id: "c1", service_id: "s1" },
    {
      kind: "read",
      cluster_id: "c1",
      service_id: "s1",
      file_id: "opaque",
      lines: 500,
    },
  ]);
  fireEvent.change(screen.getByLabelText("过滤当前内容"), {
    target: { value: "error[1]" },
  });
  expect(output.textContent).toBe("error[1]");
});

it("machine aliases round trip as a list when an owner edits the resource", async () => {
  const machine = {
    id: "m1",
    name: "node-one",
    address: "192.0.2.1",
    ssh_port: 22,
    ssh_user: "operator",
    aliases: ["node-one", "node-one.example"],
    revision: 1,
    creator_id: "u1",
  };
  let saved: any;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") saved = JSON.parse(String(init.body));
      return response(machine);
    }),
  );
  render(
    <InventoryPage
      kind="machines"
      admin={false}
      userId="u1"
      onDirty={() => {}}
      detailOnly
      initialMachineId="m1"
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "编辑资源" }));
  const input = screen.getByLabelText("主机别名");
  expect(input).toHaveValue("node-one, node-one.example");
  fireEvent.change(input, {
    target: { value: "node-one, node-one.example\nextra" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存资源" }));
  await waitFor(() =>
    expect(saved?.aliases).toEqual(["node-one", "node-one.example", "extra"]),
  );
});

it("opens a direct log URL in the authenticated app rather than cluster overview", async () => {
  window.history.replaceState(null, "", "/#/clusters/c1/logs/s1");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      response(
        path.endsWith("/auth/me")
          ? {
              id: "u1",
              username: "member",
              email: "member@example.test",
              role: "member",
              csrf_token: "csrf",
            }
          : path.endsWith("/remote-targets")
            ? {
                items: [target],
                services: [{ ...service, can_read_logs: false }],
              }
            : cluster,
      ),
    ),
  );
  const { App } = await import("../../App");
  render(<App />);
  await screen.findByRole("heading", { name: "test-cluster · 服务日志" });
  expect(screen.queryByRole("button", { name: "发现集群" })).toBeNull();
  window.history.replaceState(null, "", "/");
});
