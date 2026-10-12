import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ClusterResources } from "./ClusterResources";
import { useResourceWorkspace } from "./useResourceWorkspace";

vi.mock("./useResourceWorkspace", () => ({ useResourceWorkspace: vi.fn() }));
afterEach(cleanup);

function workspace(active: boolean, state?: string) {
  vi.mocked(useResourceWorkspace).mockReturnValue({
    snapshot: null, error: "", loading: false, active,
    operations: state ? [{ id: "operation", action: "cache.stop", state }] : [],
    execute: vi.fn(), accept: vi.fn(), refresh: vi.fn(),
  } as unknown as ReturnType<typeof useResourceWorkspace>);
}
const page = () => <ClusterResources id="cluster" name="test" revision={1} canManage />;

test("命令提交、排队和执行显示中央动画，成功后自动消失", () => {
  workspace(false);
  const view = render(page());
  expect(screen.queryByRole("status", { name: "命令执行中" })).toBeNull();
  for (const state of [undefined, "pending", "running"]) {
    workspace(true, state);
    view.rerender(page());
    expect(screen.getByRole("status", { name: "命令执行中" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "八斗 · 九章云极吉祥物" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "查看进度" })).not.toBeDisabled();
  }
  workspace(false, "succeeded");
  view.rerender(page());
  expect(screen.queryByRole("status", { name: "命令执行中" })).toBeNull();
});

test.each(["failed", "cancelled", "interrupted"])("%s 后移除动画", (state) => {
  workspace(true, "running");
  const view = render(page());
  workspace(false, state);
  view.rerender(page());
  expect(screen.queryByRole("status", { name: "命令执行中" })).toBeNull();
});

test.each(["needs_password", "needs_trust"])("%s 时隐藏动画以便认证，恢复执行时重新显示", (state) => {
  workspace(true, state);
  const view = render(page());
  expect(screen.queryByRole("status", { name: "命令执行中" })).toBeNull();
  workspace(true, "running");
  view.rerender(page());
  expect(screen.getByRole("status", { name: "命令执行中" })).toBeTruthy();
});
