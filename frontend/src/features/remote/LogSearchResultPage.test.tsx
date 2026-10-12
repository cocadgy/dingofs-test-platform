import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LogSearchResultPage } from "./LogSearchResultPage";
import { useRemoteSession } from "./useRemoteSession";
vi.mock("./useRemoteSession", () => ({ useRemoteSession: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
test("opened result shows only matching text from selected file, not the raw log", () => {
  const start = vi.fn();
  vi.mocked(useRemoteSession).mockReturnValue({
    session: { id: "search-1", kind: "search", state: "succeeded", machine_id: "m", machine_name: "m", address: "host", ssh_user: "u", target_user: "u", cluster_id: "c", expires_at: "", result: { hits: [
      { name: "a.log", line: 1, text: "ERROR one", before: ["hidden context"], after: [] },
      { name: "b.log", line: 3, text: "ERROR other file", before: [], after: [] },
    ] } },
    start, active: false, busy: false, error: "", connected: false, close: vi.fn(), send: vi.fn(), authenticate: vi.fn(),
  });
  render(<LogSearchResultPage clusterId="c" serviceId="s" fileName="a.log" keyword="ERROR" caseSensitive={false} backUrl="#/clusters/c/logs/s" />);
  expect(screen.getByText("ERROR one")).toBeInTheDocument();
  expect(screen.queryByText("hidden context")).not.toBeInTheDocument();
  expect(screen.queryByText("ERROR other file")).not.toBeInTheDocument();
  expect(screen.queryByText(/第 1 行/)).not.toBeInTheDocument();
  expect(start).toHaveBeenCalledWith({ kind: "search", cluster_id: "c", service_id: "s", keyword: "ERROR", case_sensitive: false });
});
