import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterResourcesPage, resourceRoute } from "./ClusterResourcesPage";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("./ClusterResources", () => ({
  ClusterResources: (props: { canManage: boolean; name: string }) => (
    <div data-testid="inventory">
      {props.name}:{String(props.canManage)}
    </div>
  ),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
test("resource route supports direct links and rejects invalid paths", () => {
  expect(resourceRoute("#/clusters/cluster1/resources")).toBe("cluster1");
  expect(resourceRoute("#/clusters/%/resources")).toBeUndefined();
  expect(resourceRoute("#/clusters/cluster1")).toBeUndefined();
});
test.each([
  [false, "owner", false, "verified", true],
  [false, "other", false, "verified", false],
  [true, "other", false, "verified", true],
  [true, "owner", true, "verified", false],
  [true, "owner", false, "invalid", false],
])(
  "independent page preserves ownership and cluster availability (%s %s %s %s)",
  async (admin, userId, archived, binding, allowed) => {
    vi.mocked(api).mockResolvedValue({
      external_name: "main-dingofs",
      creator_id: "owner",
      revision: 1,
      archived,
      binding_state: binding,
    });
    render(
      <ClusterResourcesPage id="cluster1" admin={admin} userId={userId} />,
    );
    expect(await screen.findByTestId("inventory")).toHaveTextContent(
      `main-dingofs:${allowed}`,
    );
    expect(screen.getByRole("link", { name: "返回集群详情" })).toHaveAttribute(
      "href",
      "#/clusters/cluster1",
    );
    expect(api).toHaveBeenCalledTimes(1);
  },
);
test("cluster load failure is visible", async () => {
  vi.mocked(api).mockRejectedValue(new Error("集群不存在"));
  render(<ClusterResourcesPage id="missing" admin={false} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("集群不存在");
  expect(screen.queryByTestId("inventory")).not.toBeInTheDocument();
});
