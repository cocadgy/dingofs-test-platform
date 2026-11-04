import { StrictMode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useResourceWorkspace } from "./useResourceWorkspace";
import { api } from "../../api/client";
import type { ResourceOperation, ResourceSnapshot } from "./types";
vi.mock("../../api/client", () => ({ api: vi.fn(), ApiError: class extends Error {} }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

test("page entry refreshes both inventories sequentially, and reentry queries again", async () => {
  const queries: string[] = [];
  let operations: ResourceOperation[] = [];
  const snapshot = (): ResourceSnapshot => ({ machines: [], resources: [], operations,
    catalog: [
      { action: "fs.list", label: "文件系统", section: "filesystem", mutating: false, fields: [] },
      { action: "cache.list", label: "缓存组", section: "cache", mutating: false, fields: [] },
    ],
  });
  vi.mocked(api).mockImplementation(async (_path, method, body) => {
    if (method === "POST") {
      const action = (body as { action: string }).action;
      queries.push(action);
      const op = { id: String(queries.length), action, state: "pending" };
      operations = [op, ...operations];
      return op as never;
    }
    return snapshot() as never;
  });
  const open = () => renderHook(() => useResourceWorkspace({ id: "cluster", name: "test", revision: 1, canManage: true }),
    { wrapper: ({ children }) => <StrictMode>{children}</StrictMode> });
  const view = open();
  await waitFor(() => expect(queries).toEqual(["fs.list"]));
  await waitFor(() => expect(view.result.current.operations[0]?.state).toBe("pending"));
  act(() => {
    operations = [{ ...operations[0], state: "succeeded" }];
    view.result.current.accept(operations[0]);
  });
  await waitFor(() => expect(queries).toEqual(["fs.list", "cache.list"]));
  await waitFor(() => expect(view.result.current.operations.some((op) => op.action === "cache.list")).toBe(true));
  act(() => {
    operations = operations.map((op) => ({ ...op, state: "succeeded" }));
    view.result.current.accept(operations[0]);
  });
  await waitFor(() => expect(view.result.current.active).toBe(false));
  view.unmount();
  open();
  await waitFor(() => expect(queries).toEqual(["fs.list", "cache.list", "fs.list"]));
});
