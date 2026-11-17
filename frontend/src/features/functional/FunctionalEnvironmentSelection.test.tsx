import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FunctionalPage } from "./FunctionalPage";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
test("submits selected versioned environment profile", async () => {
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path === "/functional/options")
      return {
        digest: "a".repeat(64),
        modules: {
          basic_file_operation: [
            { path: "smoke/a.yaml", id: "x", name: "read", run_level: "smoke" },
          ],
        },
        clusters: [{ id: "c1", name: "cluster", machine: "node" }],
        environments: ["env_old"],
      };
    if (path === "/functional/environments")
      return [
        {
          id: "p1",
          name: "custom",
          revision: 2,
          enabled: true,
          source_kind: "custom",
          cluster_id: "c1",
          validation: "needs_validation",
        },
      ];
    if (path === "/functional/environments/p1/validate?cluster_id=c1")
      return { valid: true };
    if (path === "/functional/runs" && method === "POST")
      return { id: "run1", state: "queued", snapshot: { selected: {} } };
    if (path === "/functional/runs") return [];
    return { id: "run1", state: "queued", snapshot: { selected: {} } };
  });
  window.location.hash = "#/functional/new";
  render(<FunctionalPage />);
  await screen.findByRole("option", { name: /custom/ });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: /启动 1 个用例/ })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: /启动 1 个用例/ }));
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.find(
          (c) => c[0] === "/functional/runs" && c[1] === "POST",
        )?.[2],
    ).toMatchObject({
      environment_profile_id: "p1",
      environment_profile_revision: 2,
    }),
  );
});

test("blocks a preset whose target validation fails", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/functional/options")
      return {
        digest: "a".repeat(64),
        modules: {
          basic_file_operation: [
            { path: "a.yaml", id: "x", name: "read", run_level: "smoke" },
          ],
        },
        clusters: [
          {
            id: "c1",
            name: "cluster",
            machine: "node",
            mds_addresses: ["10.0.0.1:6900"],
          },
        ],
        environments: [],
      };
    if (path === "/functional/environments")
      return [
        {
          id: "p1",
          name: "env_wrong",
          revision: 1,
          enabled: true,
          source_kind: "predefined",
          cluster_id: null,
          validation: "source_only",
          display: { mds_addresses: ["10.0.0.1:6900"] },
        },
      ];
    if (path.includes("/validate")) throw new Error("客户端主机与集群不一致");
    return [];
  });
  window.location.hash = "#/functional/new";
  render(<FunctionalPage />);
  await screen.findByRole("option", { name: /env_wrong/ });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "选择 basic_file_operation 全部用例",
    }),
  );
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    expect.stringContaining("客户端主机与集群不一致"),
  );
  expect(
    screen
      .getByRole("button", { name: /启动 1 个用例/ })
      .hasAttribute("disabled"),
  ).toBe(true);
});
