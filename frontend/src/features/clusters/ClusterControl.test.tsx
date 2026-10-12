import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterControl } from "./ClusterControl";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(api).mockReset();
});
const props = {
  id: "c1",
  name: "main-dingofs",
  revision: 3,
  canOperate: true,
  services: [{ id: "abc123", role: "mds", host: "node" }],
  onComplete: vi.fn(),
};
test("cancelling confirmation sends no command", () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ClusterControl {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "停止" }));
  expect(window.confirm).toHaveBeenCalledWith(
    expect.stringContaining("main-dingofs"),
  );
  expect(api).not.toHaveBeenCalled();
});
test.each(["all", "role", "service"])(
  "submits only the confirmed %s target",
  async (scope) => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api).mockResolvedValue({
      id: "op",
      kind: "restart",
      state: "succeeded",
      result: { stdout: "ok" },
    });
    render(<ClusterControl {...props} />);
    fireEvent.change(screen.getByLabelText("操作范围"), {
      target: { value: scope },
    });
    if (scope !== "all")
      fireEvent.change(screen.getByLabelText("操作目标"), {
        target: { value: scope === "role" ? "mds" : "abc123" },
      });
    fireEvent.click(screen.getByRole("button", { name: "重启" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/clusters/c1/control", "POST", {
        base_revision: 3,
        action: "restart",
        scope,
        target: scope === "all" ? null : scope === "role" ? "mds" : "abc123",
        confirmed: true,
      }),
    );
  },
);
test("other users cannot operate", () => {
  render(<ClusterControl {...props} canOperate={false} />);
  for (const name of ["启动", "停止", "重启"])
    expect(screen.getByRole("button", { name })).toBeDisabled();
});
