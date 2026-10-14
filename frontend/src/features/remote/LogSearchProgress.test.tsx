import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LogSearchProgress } from "./LogSearchProgress";
afterEach(() => { cleanup(); vi.useRealTimers(); });
test("popup progress advances by completed files and reaches 100% on success", () => {
  vi.useFakeTimers();
  const base = { scanned_bytes: 20, hits: 1, total_files: 2 };
  const { rerender } = render(<LogSearchProgress active state="running" progress={{ ...base, completed_files: 0 }} />);
  expect(screen.getByRole("status", { name: "日志搜索中" }).querySelector(".badou--animated")).toBeTruthy();
  expect(screen.getByRole("progressbar", { name: "搜索进度" })).toHaveAttribute("value", "0");
  rerender(<LogSearchProgress active state="running" progress={{ ...base, completed_files: 1 }} />);
  expect(screen.getByRole("progressbar", { name: "搜索进度" })).toHaveAttribute("value", "1");
  expect(screen.getByRole("progressbar", { name: "搜索进度" })).toHaveAttribute("max", "2");
  rerender(<LogSearchProgress active={false} state="succeeded" progress={{ ...base, completed_files: 2 }} />);
  expect(screen.getByRole("progressbar", { name: "搜索进度" })).toHaveAttribute("value", "2");
  expect(screen.getByRole("progressbar", { name: "搜索进度" })).toHaveAttribute("max", "2");
  expect(screen.getByText("100%")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(600));
  expect(screen.queryByRole("progressbar", { name: "搜索进度" })).not.toBeInTheDocument();
});

test("an early limit does not claim all files were searched", () => {
  const progress = { completed_files: 1, total_files: 3, scanned_bytes: 10, hits: 2 };
  const { rerender } = render(<LogSearchProgress active state="running" progress={progress} />);
  rerender(<LogSearchProgress active={false} state="succeeded" progress={progress} />);
  expect(screen.queryByRole("progressbar", { name: "搜索进度" })).not.toBeInTheDocument();
});

test("popup cancellation calls the search close action", () => {
  const onCancel = vi.fn();
  render(<LogSearchProgress active state="running" onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("button", { name: "取消搜索" }));
  expect(onCancel).toHaveBeenCalledOnce();
});
