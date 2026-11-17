import { act, renderHook, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { useResourceWorkspace } from "./useResourceWorkspace";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
test("batch commands wait for confirmation, cancellation sends nothing, and confirmation submits once", async () => {
  const snapshot = { catalog: [], operations: [], resources: [], machines: [] };
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? { id: "sent", action: "fs.delete_batch", state: "pending" }
      : snapshot,
  );
  const { result } = renderHook(() =>
    useResourceWorkspace({
      id: "cluster",
      name: "测试集群",
      revision: 1,
      canManage: true,
    }),
  );
  await waitFor(() => expect(result.current.snapshot).toBeDefined());
  const action = {
    action: "fs.delete_batch",
    label: "批量删除",
    section: "filesystem" as const,
    mutating: true,
    fields: [],
  };
  let promise: Promise<void>;
  act(() => {
    promise = result.current.execute(action, { fs_names: ["one", "two"] });
  });
  await waitFor(() => expect(result.current.confirmation).toBeDefined());
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
  await act(async () => {
    result.current.resolveConfirmation(false);
    await promise;
  });
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
  act(() => {
    promise = result.current.execute(action, { fs_names: ["one", "two"] });
  });
  await waitFor(() => expect(result.current.confirmation).toBeDefined());
  await act(async () => {
    result.current.resolveConfirmation(true);
    await promise;
  });
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    1,
  );
  expect(
    vi.mocked(api).mock.calls.find((c) => c[1] === "POST")?.[2],
  ).toMatchObject({
    parameters: { fs_names: ["one", "two"] },
    confirmed: true,
  });
});
