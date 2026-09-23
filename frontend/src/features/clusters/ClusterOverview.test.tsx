import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, it, expect, vi } from "vitest";
import { useState } from "react";
import { ClusterOverview, initialState } from "./ClusterOverview";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("shows uncollected and same-name clusters, filters all rows and opens details", async () => {
  const rows = Array.from({ length: 25 }, (_, i) => ({
    id: "c" + i,
    name: "main",
    external_name: "main",
    os_user: "user" + i,
    machine_name: "node",
    machine_address: "10.0.0.1",
    state: "unknown",
    binding_state: "verified",
    archived: false,
    revision: 1,
    status_attempt_state: "never",
    cluster_kind: null,
    node_count: null,
    service_count: null,
    running_instances: null,
    expected_instances: null,
    status_success_at: null,
  }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ items: rows, total: 25 }))),
  );
  const open = vi.fn();
  function Harness() {
    const [state, setState] = useState(initialState);
    return (
      <ClusterOverview state={state} onStateChange={setState} onOpen={open} />
    );
  }
  render(<Harness />);
  await screen.findByText("user0");
  expect(screen.getAllByRole("columnheader")).toHaveLength(10);
  fireEvent.change(screen.getByLabelText("搜索执行用户"), {
    target: { value: "user24" },
  });
  fireEvent.click(screen.getByText("user24"));
  expect(open).toHaveBeenCalledWith("c24");
  expect(screen.getByText("未采集")).toBeTruthy();
});
