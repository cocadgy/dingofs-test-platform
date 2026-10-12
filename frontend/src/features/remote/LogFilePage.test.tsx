import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LogPage } from "./LogPage";
import { remoteRoute } from "./routes";

const name = "mds.INFO #1+中文.log";
function setup(
  files = [{ file_id: "fresh-list:0", name, size: 10, mtime: 1 }],
) {
  const creates: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const response = (value: unknown) => new Response(JSON.stringify(value));
      if (path.endsWith("/auth/me"))
        return response({
          id: "u1",
          username: "owner",
          email: "user@example.test",
          role: "admin",
          csrf_token: "test",
        });
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
        return response({ name: "daily", os_user: "ops" });
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      const request = JSON.parse(String(init?.body));
      creates.push(request);
      return response({
        id: `r${creates.length}`,
        kind: request.kind,
        state: "succeeded",
        result:
          request.kind === "files"
            ? { files }
            : {
                text: "log content",
                cursor: { device: 1, inode: 2, offset: 11 },
              },
      });
    }),
  );
  return creates;
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

test("file URL retains Unicode and reserved characters while existing log and terminal routes remain valid", () => {
  expect(
    remoteRoute("#/clusters/c1/logs/s1?file=" + encodeURIComponent(name)),
  ).toMatchObject({
    clusterId: "c1",
    targetId: "s1",
    kind: "logs",
    fileName: name,
  });
  expect(remoteRoute("#/clusters/c1/logs/s1")).toMatchObject({
    clusterId: "c1",
    targetId: "s1",
    kind: "logs",
  });
  expect(remoteRoute("#/clusters/c1/terminal/m1")).toMatchObject({
    targetId: "m1",
    kind: "terminal",
  });
});

test("single click only selects; double click opens a new file page without reading in the list page", async () => {
  const creates = setup();
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  render(<LogPage clusterId="c1" serviceId="s1" />);
  const row = await screen.findByRole("row", { name: new RegExp("mds.INFO") });
  fireEvent.click(row);
  expect(creates.map((row) => row.kind)).toEqual(["files"]);
  expect(open).not.toHaveBeenCalled();
  fireEvent.doubleClick(row);
  expect(open).toHaveBeenCalledExactlyOnceWith(
    "#/clusters/c1/logs/s1?file=" + encodeURIComponent(name),
    "_blank",
    "noopener,noreferrer",
  );
  expect(screen.queryByLabelText("日志内容")).toBeNull();
  expect(creates.map((row) => row.kind)).toEqual(["files"]);
});

test("direct file route through the app obtains fresh authorization before reading", async () => {
  const creates = setup();
  window.history.replaceState(
    null,
    "",
    "/#/clusters/c1/logs/s1?file=" + encodeURIComponent(name),
  );
  const { App } = await import("../../App");
  render(<App />);
  await waitFor(() =>
    expect(screen.getByLabelText("日志内容")).toHaveTextContent("log content"),
  );
  expect(creates).toEqual([
    { kind: "files", cluster_id: "c1", service_id: "s1" },
    {
      kind: "read",
      cluster_id: "c1",
      service_id: "s1",
      file_id: "fresh-list:0",
      lines: 500,
    },
  ]);
  expect(screen.queryByRole("table", { name: "日志文件列表" })).toBeNull();
  expect(screen.getByRole("link", { name: "返回日志列表" })).toHaveAttribute(
    "href",
    "#/clusters/c1/logs/s1",
  );
});

test("a missing or rotated file never sends its URL name as a remote path", async () => {
  const creates = setup([]);
  render(<LogPage clusterId="c1" serviceId="s1" fileName="missing.log" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("未找到日志文件");
  expect(creates.map((row) => row.kind)).toEqual(["files"]);
});

test("search result URL opens a search view instead of the original file", () => {
  expect(remoteRoute("#/clusters/c1/logs/s1?search=ERROR&match=mds.INFO&case=1")).toMatchObject({
    clusterId: "c1", targetId: "s1", searchKeyword: "ERROR", searchFile: "mds.INFO", searchCaseSensitive: true,
  });
});
