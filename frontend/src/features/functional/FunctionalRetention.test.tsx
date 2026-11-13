import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FunctionalPage } from "./FunctionalPage";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.mocked(api).mockReset(); window.location.hash = "#/"; });

function setup(remaining: string[], error = false, canManage = true) {
  window.location.hash = "#/functional/retained";
  let checked = false;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/functional/options") return { clusters: [], modules: {}, digest: "a".repeat(64) };
    if (path === "/functional/environments") return [];
    if (path === "/functional/runs/retained/resources/verify") {
      expect(method).toBe("POST");
      expect(body).toBeUndefined();
      if (error) throw new Error("远端结束证据未确认");
      checked = true;
      return { owner: "functional:retained", remote_ended: true, recovery_ok: true,
        verified_resources: [], remaining_resources: remaining, observed_at: "2026-11-10T00:00:00Z" };
    }
    if (path === "/functional/runs/retained") return {
      id: "retained", name: checked ? "已刷新任务" : "保留现场任务", version: 2, can_manage: canManage,
      state: "needs_attention", snapshot: {}, children: [], phase: "保留现场", log: "", error: "",
    };
    throw new Error("unexpected API: " + path);
  });
  render(<FunctionalPage />);
}

function setupRelease(error = false, isAdmin = true) {
  window.location.hash = "#/functional/retained";
  let released = false;
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/functional/options") return { clusters: [], modules: {}, digest: "a".repeat(64) };
    if (path === "/functional/environments") return [];
    if (path.endsWith("/release-retained") || path.endsWith("/reacquire-retained")) {
      expect(method).toBe("POST"); expect(body).toEqual({ confirmed: true });
      if (error) throw new Error("远端结束身份无法重新确认");
      released = path.endsWith("/release-retained");
      return { released, retained_count: 2 };
    }
    if (path === "/functional/runs/retained") return {
      id: "retained", name: "保留现场任务", version: 2, can_manage: true, can_release_retained: isAdmin,
      state: "needs_attention", snapshot: {}, children: [], phase: "保留现场", log: "", error: "",
      result: released ? { retention_release: { released: true, retained_count: 2 } } : {},
    };
    throw new Error("unexpected API: " + path);
  });
  render(<FunctionalPage />);
}

test("admin confirms release, retains warning, and can reacquire before cleanup", async () => {
  setupRelease(); vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(await screen.findByRole("button", { name: "保留残留并释放占用" }));
  expect(await screen.findByText(/残留已保留、占用已释放/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "重新占用以清理" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已重新占用"));
});

test("cancelled acknowledgement sends no release request", async () => {
  setupRelease(); vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(await screen.findByRole("button", { name: "保留残留并释放占用" }));
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/release-retained"))).toHaveLength(0);
});

test("release failure never displays successful release", async () => {
  setupRelease(true); vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(await screen.findByRole("button", { name: "保留残留并释放占用" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("远端结束身份无法重新确认");
  expect(screen.queryByText(/残留已保留、占用已释放/)).not.toBeInTheDocument();
});

test("non-admin manager has no retention release button", async () => {
  setupRelease(false, false);
  await screen.findByRole("heading", { name: "保留现场任务" });
  expect(screen.queryByRole("button", { name: "保留残留并释放占用" })).not.toBeInTheDocument();
});

test("readonly residual verification reports remaining leases and refreshes the task", async () => {
  setup(["cluster:c1"]);
  fireEvent.click(await screen.findByRole("button", { name: "重新检查残留资源" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("仍有 1 项资源未确认释放"));
  expect(await screen.findByRole("heading", { name: "已刷新任务" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("cleanup"))).toBe(false);
});

test("verified absence says resources were checked without claiming cleanup", async () => {
  setup([]);
  fireEvent.click(await screen.findByRole("button", { name: "重新检查残留资源" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已确认资源释放"));
});

test("unverified end evidence is surfaced and does not imply release", async () => {
  setup([], true);
  fireEvent.click(await screen.findByRole("button", { name: "重新检查残留资源" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("远端结束证据未确认");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("read-only viewers cannot trigger residual verification", async () => {
  setup([], false, false);
  await screen.findByRole("heading", { name: "保留现场任务" });
  expect(screen.queryByRole("button", { name: "重新检查残留资源" })).not.toBeInTheDocument();
});
