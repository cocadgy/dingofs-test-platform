import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { useResourceWorkspace } from "./useResourceWorkspace";

vi.mock("../../api/client", async (original) => ({
  ...(await original<typeof import("../../api/client")>()),
  api: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

test.each(["fs.delete", "fs.delete_batch"])(
  "%s completion refreshes the filesystem list once", async (action) => {
    const snapshot = { catalog: [{ action: "fs.list", label: "文件系统列表",
      section: "filesystem", mutating: false, fields: [] }], resources: [],
      machines: [], operations: [] };
    vi.mocked(api).mockImplementation(async (_path, method) => method === "POST"
      ? { id: "fresh-list", action: "fs.list", state: "succeeded",
          result: { steps: [{ data: { fs_infos: [{ fs_name: "remaining" }] } }] } }
      : snapshot);
    const { result } = renderHook(() => useResourceWorkspace({
      id: "cluster", name: "cluster", revision: 1, canManage: true,
    }));
    await waitFor(() => expect(result.current.snapshot).toBeDefined());
    await waitFor(() => expect(result.current.active).toBe(false));
    vi.mocked(api).mockClear(); // Ignore the fresh inventory query on page entry.
    act(() => result.current.accept({ id: "delete", action, state: "running" }));
    expect(vi.mocked(api).mock.calls.filter(call => call[1] === "POST")).toHaveLength(0);
    act(() => result.current.accept({ id: "delete", action, state: "succeeded" }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.filter(call => call[1] === "POST")).toHaveLength(1));
    expect(vi.mocked(api).mock.calls.find(call => call[1] === "POST")?.[2])
      .toMatchObject({ action: "fs.list", parameters: {}, confirmed: false });
    act(() => result.current.accept({ id: "delete", action, state: "succeeded" }));
    expect(vi.mocked(api).mock.calls.filter(call => call[1] === "POST")).toHaveLength(1);
  },
);
