import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LogDirectorySearch } from "./LogDirectorySearch";
import { useRemoteSession } from "./useRemoteSession";
vi.mock("./useRemoteSession", () => ({ useRemoteSession: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
test("full search submits selected bounds and result link retains them", () => {
  const start = vi.fn();
  vi.mocked(useRemoteSession).mockReturnValue({
    session: { id: "search", kind: "search", state: "succeeded", machine_id: "m", machine_name: "m", address: "host", ssh_user: "u", target_user: "u", cluster_id: "c", expires_at: "", result: { hits: [
      { name: "a.log", line: 1, text: "TARGET", before: [], after: [] },
    ] } },
    start, active: false, busy: false, error: "", connected: false, close: vi.fn(), send: vi.fn(), authenticate: vi.fn(),
  });
  render(<LogDirectorySearch clusterId="c" serviceId="s" fileUrl={name => `#/clusters/c/logs/s?file=${name}`} />);
  fireEvent.change(screen.getByLabelText("日志搜索关键词"), { target: { value: "TARGET" } });
  fireEvent.change(screen.getByLabelText("扫描方式"), { target: { value: "full" } });
  fireEvent.change(screen.getByLabelText("总扫描量"), { target: { value: "256" } });
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));
  expect(start).toHaveBeenCalledWith(expect.objectContaining({ scan_mode: "full", max_total_mb: 256, max_files: 200, max_hits: 200 }));
  const url = screen.getByRole("link", { name: "打开查询结果" }).getAttribute("href") || "";
  expect(url).toContain("mode=full");
  expect(url).toContain("max_total_mb=256");
});

test("unlimited choices are submitted and popup cancellation closes the session", () => {
  const start = vi.fn(), close = vi.fn();
  vi.mocked(useRemoteSession).mockReturnValue({
    session: undefined, start, active: true, busy: true, error: "", connected: false, close, send: vi.fn(), authenticate: vi.fn(),
  });
  render(<LogDirectorySearch clusterId="c" serviceId="s" fileUrl={name => `#/clusters/c/logs/s?file=${name}`} />);
  fireEvent.change(screen.getByLabelText("日志搜索关键词"), { target: { value: "ERROR" } });
  fireEvent.change(screen.getByLabelText("总扫描量"), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText("最多结果"), { target: { value: "0" } });
  expect(screen.getByLabelText("总扫描量")).toHaveValue("0");
  expect(screen.getByLabelText("最多结果")).toHaveValue("0");
  fireEvent.click(screen.getByRole("button", { name: "取消搜索" }));
  expect(close).toHaveBeenCalledOnce();
});

test("unlimited choices are sent as zero when a search starts", () => {
  const start = vi.fn();
  vi.mocked(useRemoteSession).mockReturnValue({
    session: undefined, start, active: false, busy: false, error: "", connected: false, close: vi.fn(), send: vi.fn(), authenticate: vi.fn(),
  });
  render(<LogDirectorySearch clusterId="c" serviceId="s" fileUrl={name => `#/clusters/c/logs/s?file=${name}`} />);
  fireEvent.change(screen.getByLabelText("日志搜索关键词"), { target: { value: "ERROR" } });
  fireEvent.change(screen.getByLabelText("总扫描量"), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText("最多结果"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));
  expect(start).toHaveBeenCalledWith(expect.objectContaining({ max_total_mb: 0, max_hits: 0 }));
});
