import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { useResourceWorkspace } from "./useResourceWorkspace";
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  api: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function setup(canManage = true) {
  const snapshot = {
    catalog: [
      {
        action: "cache.list",
        label: "缓存组与成员列表",
        section: "cache",
        mutating: false,
        fields: [],
      },
    ],
    resources: [],
    machines: [],
    operations: [],
  };
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? {
          id: "listing",
          action: "cache.list",
          state: "succeeded",
          result: { steps: [] },
        }
      : snapshot,
  );
  return renderHook(() =>
    useResourceWorkspace({ id: "c", name: "cluster", revision: 1, canManage }),
  );
}
test("successful creation refreshes remote list once without resubmitting creation", async () => {
  const { result } = setup();
  await waitFor(() => expect(result.current.snapshot).toBeDefined());
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
  act(() =>
    result.current.accept({
      id: "create",
      action: "cache.create",
      state: "running",
    }),
  );
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
  act(() =>
    result.current.accept({
      id: "create",
      action: "cache.create",
      state: "succeeded",
    }),
  );
  await waitFor(() =>
    expect(
      vi.mocked(api).mock.calls.filter((c) => c[1] === "POST"),
    ).toHaveLength(1),
  );
  expect(
    vi.mocked(api).mock.calls.find((c) => c[1] === "POST")?.[2],
  ).toMatchObject({ action: "cache.list", parameters: {}, confirmed: false });
  act(() =>
    result.current.accept({
      id: "create",
      action: "cache.create",
      state: "succeeded",
    }),
  );
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    1,
  );
});
test.each(["failed", "cancelled"])(
  "refreshes after %s creation to show completed batch members",
  async (state) => {
    const { result } = setup();
    await waitFor(() => expect(result.current.snapshot).toBeDefined());
    act(() =>
      result.current.accept({ id: "create", action: "cache.create", state }),
    );
    await waitFor(() => expect(
      vi.mocked(api).mock.calls.filter((c) => c[1] === "POST"),
    ).toHaveLength(1));
  },
);
test("read-only viewers never trigger a remote query", async () => {
  const { result } = setup(false);
  await waitFor(() => expect(result.current.snapshot).toBeDefined());
  act(() =>
    result.current.accept({
      id: "create",
      action: "cache.create",
      state: "succeeded",
    }),
  );
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
});

test.each(["cache.stop", "cache.delete", "cache.delete_batch"])(
  "%s completion refreshes actual inventory",
  async (action) => {
    const { result } = setup();
    await waitFor(() => expect(result.current.snapshot).toBeDefined());
    act(() =>
      result.current.accept({ id: "mutation", action, state: "failed" }),
    );
    await waitFor(() =>
      expect(
        vi.mocked(api).mock.calls.filter((c) => c[1] === "POST"),
      ).toHaveLength(1),
    );
    expect(
      vi.mocked(api).mock.calls.find((c) => c[1] === "POST")?.[2],
    ).toMatchObject({ action: "cache.list" });
  },
);


test.each(["cache.leave", "cache.unlock", "cache.weight"])("%s refreshes member inventory after completion", async (action) => {
  const { result } = setup();
  await waitFor(() => expect(result.current.snapshot).toBeDefined());
  act(() => result.current.accept({id:"member-change",action,state:"succeeded"}));
  await waitFor(() => expect(vi.mocked(api).mock.calls.filter(call => call[1] === "POST")).toHaveLength(1));
  expect(vi.mocked(api).mock.calls.find(call => call[1] === "POST")?.[2]).toMatchObject({action:"cache.list"});
});
