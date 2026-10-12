import { StrictMode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterDetail } from "./ClusterDetail";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
test("detail links to a separate resource page without fetching inventory", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  const inventory = {
    catalog: [],
    machines: [],
    resources: [],
    operations: [],
  };
  const detail = {
    id: "cluster1",
    creator_id: "owner",
    name: "alias",
    external_name: "main-dingofs",
    revision: 1,
    archived: false,
    binding_state: "verified",
    node_links: {},
    node_match_states: {},
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/remote-targets")) return { items: [], services: [] };
    if (path.endsWith("/resources")) return inventory;
    if (path.endsWith("/refresh-status"))
      return { id: "status1", kind: "status", state: "succeeded", result: {} };
    if (path.endsWith("/topology"))
      return {
        id: "topology1",
        kind: "topology",
        state: "succeeded",
        result: { stdout: "global:\n  user: root" },
      };
    return detail;
  });
  render(
    <StrictMode>
      <ClusterDetail
        id="cluster1"
        admin
        userId="owner"
        onBack={() => {}}
        onDirty={() => {}}
        onDiscover={() => {}}
      />
    </StrictMode>,
  );
  await screen.findByLabelText("topology.yaml 内容");
  await waitFor(() =>
    expect(screen.queryByText("正在读取资源记录…")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("link", { name: "资源管理" })).toHaveAttribute(
    "href",
    "#/clusters/cluster1/resources",
  );
  expect(screen.queryByText("集群资源管理")).not.toBeInTheDocument();
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith("/resources")),
  ).toBe(false);
  expect(
    errors.mock.calls.filter((args) => String(args[0]).includes("same key")),
  ).toEqual([]);
});
