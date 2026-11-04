import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceNavigation } from "./ResourceNavigation";
import type { ResourceOperation, ResourceSnapshot } from "./types";

afterEach(cleanup);
const snapshot: ResourceSnapshot = { catalog: [], machines: [], operations: [], resources: [
  { id: "old", kind: "mount", name: "/old", state: "deleted", data: {}, created_at: "" },
  { id: "stale", kind: "mount", name: "/stale", state: "mounted", data: {}, created_at: "" },
] };
const fs: ResourceOperation = { id: "fs", action: "fs.list", state: "succeeded", result: { steps: [{ data: { result: { fs_infos: [
  { fs_name: "live", mount_points: [{ client_id: "1" }, { client_id: "2" }] },
  { fs_name: "empty" }, { fs_name: "old_DELETE_1", mount_points: [{ client_id: "3" }] },
] } } }] } };
const props = { area: "mount" as const, operationCount: 0, onChange: vi.fn() };
function count(label: string) { return screen.getByRole("button", { name: new RegExp(label) }).textContent; }

test("entry hides historical counts; fresh query excludes DELETE and counts MDS mounts", () => {
  const { rerender } = render(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [{ ...fs, id: "old-fs" }] }} />);
  expect(count("文件系统")).toBe("文件系统—");
  expect(count("挂载点")).toBe("挂载点—");
  rerender(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [fs] }} />);
  expect(count("文件系统")).toBe("文件系统2");
  expect(count("挂载点")).toBe("挂载点2");
  rerender(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [{ ...fs, id: "next", state: "failed" }, fs] }} />);
  expect(count("挂载点")).toBe("挂载点—");
});

test("only cache groups with online members count", () => {
  const { rerender } = render(<ResourceNavigation {...props} snapshot={snapshot} />);
  const cache: ResourceOperation = { id: "cache", action: "cache.list", state: "succeeded", result: { steps: [{ data: {
    groups: { result: { group_names: ["online", "partial", "offline", "empty"] } },
    members: { result: { members: [
      { member_id: "a", group_name: "online", state: 1, ip: "127.0.0.1", port: 1 },
      { member_id: "b", group_name: "partial", state: 1, ip: "127.0.0.1", port: 2 },
      { member_id: "c", group_name: "partial", state: 3, ip: "127.0.0.1", port: 3 },
      { member_id: "d", group_name: "offline", state: 3, ip: "127.0.0.1", port: 4 },
    ] } },
  } }] } };
  rerender(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [cache] }} />);
  expect(count("缓存组")).toBe("缓存组2");
});

test("reentering requires a new query", () => {
  const view = render(<ResourceNavigation {...props} snapshot={snapshot} />);
  view.rerender(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [fs] }} />);
  expect(count("挂载点")).toBe("挂载点2");
  view.unmount();
  render(<ResourceNavigation {...props} snapshot={{ ...snapshot, operations: [fs] }} />);
  expect(count("挂载点")).toBe("挂载点—");
});
