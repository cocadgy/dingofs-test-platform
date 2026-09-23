import { render, screen, cleanup } from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { ClusterPage } from "../clusters/ClusterPage";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});
it("cluster management exposes discovery instead of manual context fields", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }))),
  );
  render(<ClusterPage admin onDirty={vi.fn()} />);
  await screen.findByRole("button", { name: "发现集群" });
  expect(screen.queryByLabelText("管理上下文")).toBeNull();
  expect(screen.queryByLabelText("dingo 工具路径")).toBeNull();
});
