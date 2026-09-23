import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { DiscoverClusters } from "./DiscoverClusters";
import { OperationAuthDialog } from "./OperationAuthDialog";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("discovers with machine and username only and imports selected names", async () => {
  const calls: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: any, opts: any) => {
      const body = opts?.body ? JSON.parse(opts.body) : null;
      calls.push({ url: String(url), body });
      let data: any = {
        items: [
          {
            id: "m1",
            name: "node",
            address: "node",
            revision: 1,
            ssh_user: "zetyun",
          },
        ],
        total: 1,
      };
      if (String(url).includes("cluster-discoveries"))
        data = String(url).endsWith("/import")
          ? {
              created: [{ id: "c1", name: "main-dingofs" }],
              existing: [],
              needs_confirmation: [],
            }
          : {
              id: "o1",
              state: "succeeded",
              result: { names: ["main-dingofs", "test-dingofs"] },
            };
      return new Response(JSON.stringify(data));
    }),
  );
  const done = vi.fn();
  render(<DiscoverClusters admin onImported={done} onClose={vi.fn()} />);
  await screen.findByRole("option", { name: /node/ });
  fireEvent.change(screen.getByLabelText("执行机器"), {
    target: { value: "m1" },
  });
  expect(screen.getByLabelText("执行用户")).toHaveValue("zetyun");
  expect(screen.queryByLabelText("dingo 工具路径")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查询集群" }));
  fireEvent.click(await screen.findByLabelText("main-dingofs"));
  fireEvent.click(screen.getByRole("button", { name: "导入所选集群" }));
  await waitFor(() => expect(done).toHaveBeenCalledWith(["c1"]));
  expect(
    calls.find((c) => c.url.endsWith("/cluster-discoveries")).body,
  ).toEqual({ machine_id: "m1", machine_revision: 1, target_user: "zetyun" });
});
it("names the authentication account and submits password only to its challenge", async () => {
  const fetch = vi.fn(
    async () => new Response(JSON.stringify({ id: "op", state: "succeeded" })),
  );
  vi.stubGlobal("fetch", fetch);
  render(
    <OperationAuthDialog
      operation={{
        id: "op",
        kind: "discover",
        state: "needs_password",
        machine_id: "m",
        machine_name: "node",
        ssh_user: "zetyun",
        target_user: "root",
        auth_account: "zetyun",
        challenge: "challenge",
        error_code: "needs_password",
        message: "需要认证",
        result: null,
        cluster_id: null,
        expires_at: "2030-01-01",
      }}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText(/需要验证账号：zetyun/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("认证密码"), {
    target: { value: "sentinel" },
  });
  fireEvent.click(screen.getByRole("button", { name: "验证并继续" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  expect(screen.getByLabelText("认证密码")).toHaveValue("");
});

it("only offers the member's own machines for discovery", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            total: 3,
            items: [
              {
                id: "mine",
                name: "my-node",
                address: "mine.test",
                creator_id: "alice",
                archived: false,
              },
              {
                id: "other",
                name: "other-node",
                address: "other.test",
                creator_id: "bob",
                archived: false,
              },
              {
                id: "legacy",
                name: "legacy-node",
                address: "legacy.test",
                creator_id: null,
                archived: false,
              },
            ],
          }),
        ),
    ),
  );
  render(
    <DiscoverClusters
      admin={false}
      userId="alice"
      onImported={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  await screen.findByRole("option", { name: /my-node/ });
  expect(screen.queryByRole("option", { name: /other-node/ })).toBeNull();
  expect(screen.queryByRole("option", { name: /legacy-node/ })).toBeNull();
});
