import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { CacheTagSelector } from "./CacheTagSelector";
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); });
const old = { name: "old", updated_at: "2026-09-01T00:00:00Z", digest: "sha256:" + "a".repeat(64), available: true };
const latest = { name: "latest", updated_at: "2026-11-01T00:00:00Z", digest: "sha256:" + "b".repeat(64), available: true };

test("lists newest tags first and selects the returned immutable digest without starting a download", async () => {
  vi.mocked(api).mockResolvedValue({ items: [old, latest], count: 2, next_page: null });
  const selected = vi.fn();
  render(<CacheTagSelector tag="" digest="" onChange={selected} />);
  await screen.findByRole("option", { name: /latest/ });
  expect(screen.getAllByRole("option").slice(1).map(item => (item as HTMLOptionElement).value)).toEqual(["latest", "old"]);
  fireEvent.change(screen.getByLabelText("镜像 TAG"), { target: { value: "latest" } });
  expect(selected).toHaveBeenCalledWith("latest", latest.digest);
  expect(vi.mocked(api).mock.calls.every(([path, method]) => path.startsWith("/cache-image-tags?") && !method)).toBe(true);
});

test("supports search and pagination while retaining descending dates", async () => {
  vi.mocked(api).mockImplementation(async path => path.includes("page=2")
    ? { items: [old], count: 2, next_page: null }
    : { items: [latest], count: 2, next_page: 2 });
  render(<CacheTagSelector tag="" digest="" onChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "加载更多 TAG" }));
  await screen.findByRole("option", { name: /old/ });
  fireEvent.change(screen.getByLabelText("搜索 TAG"), { target: { value: "v5.2" } });
  fireEvent.click(screen.getByRole("button", { name: "搜索 TAG" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/cache-image-tags?page=1&search=v5.2"));
});
