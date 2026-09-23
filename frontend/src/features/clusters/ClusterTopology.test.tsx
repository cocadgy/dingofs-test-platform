import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { api } from "../../api/client";
import { ClusterTopology } from "./ClusterTopology";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
test("loads topology from the selected cluster and retains it on refresh failure", async () => {
  vi.mocked(api).mockResolvedValueOnce({
    id: "op1",
    kind: "topology",
    state: "succeeded",
    result: { stdout: "global:\n  user: jenkins\n" },
  });
  render(<ClusterTopology id="cluster1" revision={3} />);
  expect(await screen.findByText(/user: jenkins/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/clusters/cluster1/topology", "POST", {
    base_revision: 3,
  });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  vi.mocked(api).mockRejectedValueOnce(new Error("读取失败"));
  fireEvent.click(screen.getByRole("button", { name: "刷新 topology.yaml" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("读取失败"),
  );
  expect(screen.getByText(/user: jenkins/)).toBeInTheDocument();
});

test("other users view the saved topology without running a remote command", async () => {
  vi.mocked(api).mockClear();
  vi.mocked(api).mockResolvedValueOnce({
    stdout: "saved-topology: true",
    collected_at: null,
  });
  render(<ClusterTopology id="other" revision={1} canOperate={false} />);
  expect(await screen.findByText("saved-topology: true")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/clusters/other/topology");
  expect(
    screen.getByRole("button", { name: "刷新 topology.yaml" }),
  ).toBeDisabled();
});
