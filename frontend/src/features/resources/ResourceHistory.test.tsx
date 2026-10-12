import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceHistory } from "./ResourceHistory";
import { api } from "../../api/client";
import type { ResourceOperation } from "./types";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.mocked(api).mockReset();
});
const record = (id: string): ResourceOperation => ({
  id,
  action: "fs.list",
  state: "succeeded",
  result: { steps: [{ returncode: 0, stdout: "result-" + id }] },
});
const props = {
  area: "filesystem" as const,
  selectedGroup: "基础操作",
  operations: [record("new"), record("old")],
  catalog: [],
  canManage: true,
  onChange: vi.fn(),
  onShowHistory: vi.fn(),
  historySearch: "",
  setHistorySearch: vi.fn(),
  historyState: "",
  setHistoryState: vi.fn(),
};
test("only the current result is mounted; hidden completed history does not create result DOM", () => {
  const { rerender } = render(<ResourceHistory {...props} />);
  expect(screen.getByText("result-new")).toBeInTheDocument();
  expect(screen.queryByText("result-old")).not.toBeInTheDocument();
  rerender(
    <ResourceHistory {...props} area="cache" selectedGroup="缓存组操作" />,
  );
  expect(screen.queryByText("result-new")).not.toBeInTheDocument();
  expect(screen.queryByText("result-old")).not.toBeInTheDocument();
});
test("collapsed historical results mount on expansion and unmount on collapse", async () => {
  const { container } = render(<ResourceHistory {...props} area="history" />);
  expect(screen.queryByText("result-old")).not.toBeInTheDocument();
  const entries = container.querySelectorAll("details.resource-history-entry");
  expect(entries).toHaveLength(2);
  fireEvent.click(entries[1].querySelector("summary")!);
  expect(await screen.findByText("result-old")).toBeVisible();
  fireEvent.click(entries[1].querySelector("summary")!);
  await waitFor(() =>
    expect(screen.queryByText("result-old")).not.toBeInTheDocument(),
  );
});
test("filtering history only mounts the first matching result", () => {
  const { rerender } = render(<ResourceHistory {...props} area="history" />);
  rerender(<ResourceHistory {...props} area="history" historySearch="old" />);
  expect(screen.getByText("result-old")).toBeVisible();
  expect(screen.queryByText("result-new")).not.toBeInTheDocument();
});
test("a hidden active operation continues polling without rendering its result", async () => {
  const pending = { ...record("pending"), state: "pending", creator_id: "u1" };
  const done = { ...pending, state: "succeeded" };
  vi.mocked(api).mockResolvedValue(done);
  const onChange = vi.fn();
  render(
    <ResourceHistory
      {...props}
      area="cache"
      selectedGroup="缓存组操作"
      operations={[pending]}
      userId="u1"
      onChange={onChange}
    />,
  );
  expect(screen.queryByText("result-pending")).not.toBeInTheDocument();
  await waitFor(() => expect(onChange).toHaveBeenCalledWith(done));
});
