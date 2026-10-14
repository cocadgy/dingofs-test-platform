import { render, screen, cleanup } from "@testing-library/react";
import { vi, test, expect, afterEach } from "vitest";
import { InventoryPage } from "./InventoryPage";
import { MachinePage } from "./MachinePage";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});
for (const [owner, expected] of [
  ["alice", true],
  ["bob", false],
  [null, false],
] as const) {
  test(`member detail edit permission for creator ${owner}`, async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              id: "m",
              name: "node",
              creator_id: owner,
              revision: 1,
              archived: false,
              address: "node.test",
              ssh_user: "test",
              ssh_port: 22,
              tags: [],
              collection_status: "never",
            }),
          ),
      ),
    );
    render(
      <InventoryPage
        kind="machines"
        admin={false}
        userId="alice"
        onDirty={vi.fn()}
        detailOnly
        initialMachineId="m"
      />,
    );
    await screen.findByRole("heading", { name: "node" });
    expect(!!screen.queryByRole("button", { name: "编辑资源" })).toBe(expected);
  });
}
test("member can open the machine registration page", () => {
  window.history.replaceState(null, "", "/#/machines/new");
  render(<MachinePage admin={false} userId="alice" onDirty={vi.fn()} />);
  expect(
    screen.getByRole("heading", { name: "登记机器资源", level: 1 }),
  ).toBeInTheDocument();
});

test("machine owner can open a direct SSH terminal in a new tab", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    id: "m", name: "node", creator_id: "alice", revision: 1, archived: false,
    address: "node.test", ssh_user: "test", ssh_port: 22, has_ssh_password: true,
    collection_status: "never",
  }))));
  render(<InventoryPage kind="machines" admin={false} userId="alice" onDirty={vi.fn()}
    detailOnly initialMachineId="m" />);
  const link = await screen.findByRole("link", { name: "打开 SSH 终端" });
  expect(link).toHaveAttribute("href", "#/machines/m/terminal");
  expect(link).toHaveAttribute("target", "_blank");
});

test("machine viewer and archived resource cannot start SSH terminal", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    id: "m", name: "node", creator_id: "bob", revision: 1, archived: false,
    address: "node.test", ssh_user: "test", ssh_port: 22, has_ssh_password: true,
    collection_status: "never",
  }))));
  render(<InventoryPage kind="machines" admin={false} userId="alice" onDirty={vi.fn()}
    detailOnly initialMachineId="m" />);
  await screen.findByRole("heading", { name: "node" });
  expect(screen.queryByRole("link", { name: "打开 SSH 终端" })).toBeNull();
});
