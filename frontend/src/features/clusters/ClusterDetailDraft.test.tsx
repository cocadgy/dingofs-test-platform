import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterDetail } from "./ClusterDetail";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("./ClusterTopology", () => ({ ClusterTopology: () => null }));
vi.mock("./ClusterControl", () => ({ ClusterControl: () => null }));
vi.mock("./OperationAuthDialog", () => ({
  OperationAuthDialog: ({ operation, onChange }: any) => (
    <button onClick={() => onChange({ ...operation, state: "succeeded" })}>
      完成状态刷新
    </button>
  ),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
test("background refresh does not overwrite alias draft and reopening edit uses newest saved name", async () => {
  let savedName = "原别名";
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/remote-targets")) return { items: [], services: [] };
    if (path.endsWith("/refresh-status"))
      return { id: "refresh1", kind: "status", state: "pending" };
    return {
      id: "c1",
      name: savedName,
      external_name: "main-dingofs",
      revision: 1,
      creator_id: "u1",
      binding_state: "verified",
      archived: false,
    };
  });
  render(
    <ClusterDetail
      id="c1"
      admin
      userId="u1"
      onBack={() => {}}
      onDirty={() => {}}
      onDiscover={() => {}}
    />,
  );
  await screen.findByRole("button", { name: "完成状态刷新" });
  fireEvent.click(screen.getByRole("button", { name: "编辑登记信息" }));
  expect(screen.getByLabelText("别名")).toHaveValue("原别名");
  fireEvent.change(screen.getByLabelText("别名"), {
    target: { value: "未保存别名" },
  });
  savedName = "后台新别名";
  fireEvent.click(screen.getByRole("button", { name: "完成状态刷新" }));
  await waitFor(() =>
    expect(screen.getByText("别名：后台新别名")).toBeVisible(),
  );
  expect(screen.getByLabelText("别名")).toHaveValue("未保存别名");
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  fireEvent.click(screen.getByRole("button", { name: "编辑登记信息" }));
  expect(screen.getByLabelText("别名")).toHaveValue("后台新别名");
});
