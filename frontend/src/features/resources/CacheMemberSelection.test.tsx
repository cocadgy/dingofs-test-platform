import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterResources } from "./ClusterResources";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { ResourceOperation, ResourceSnapshot } from "./types";
import type { Execute } from "./useResourceWorkspace";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(api).mockReset();
});

const offline = {
  member_id: "member-offline",
  group_name: "external-group",
  ip: "10.0.0.4",
  port: 21000,
  state: 3,
};
const online = { ...offline, member_id: "member-online", state: 1 };
const unknown = { ...offline, member_id: "member-unknown", state: 0 };
function listing(
  rows: unknown[] = [offline, online, unknown],
  changes: Partial<ResourceOperation> = {},
): ResourceOperation {
  return {
    id: "list-1",
    action: "cache.list",
    state: "succeeded",
    created_at: "2026-10-09T01:00:00Z",
    result: { steps: [{ data: { members: { result: { members: rows } } } }] },
    ...changes,
  };
}
function snapshot(
  operations: ResourceOperation[] = [listing()],
): ResourceSnapshot {
  return {
    catalog: [
      {
        action: "cache.list",
        label: "缓存组与成员列表",
        section: "cache",
        mutating: false,
        fields: [],
      },
      {
        action: "cache.delete",
        label: "删除缓存组成员登记",
        section: "cache",
        mutating: true,
        fields: [
          {
            key: "member_id",
            label: "缓存组成员",
            type: "text",
            required: true,
          },
        ],
      },
      {
        action: "cache.stop",
        label: "停止缓存组",
        section: "cache",
        mutating: true,
        fields: [
          { key: "resource_id", label: "缓存组", type: "text", required: true },
        ],
      },
    ],
    machines: [],
    resources: [],
    operations,
  };
}
function setup(initial = snapshot(), execute = vi.fn<Execute>(async () => {})) {
  const props = {
    section: sections[1],
    disabled: false,
    execute,
    group: "缓存组操作",
    onGroupChange: vi.fn(),
  };
  const view = render(<ResourceSectionForm {...props} snapshot={initial} />);
  fireEvent.click(screen.getByRole("button", { name: "删除缓存组成员登记" }));
  return {
    execute,
    rerender: (next: ResourceSnapshot) =>
      view.rerender(<ResourceSectionForm {...props} snapshot={next} />),
  };
}
const selectMember = (id: string) =>
  fireEvent.change(screen.getByRole("combobox", { name: "缓存组成员" }), {
    target: { value: id },
  });
const submit = () =>
  screen.getByRole("button", { name: "执行删除缓存组成员登记" });

test("external members populate a select without managed resources; only eligible members submit their ID", async () => {
  const { execute } = setup();
  const select = screen.getByRole("combobox", { name: "缓存组成员" });
  expect(screen.queryByRole("textbox", { name: "缓存组成员" })).toBeNull();
  const option = within(select).getByRole("option", { name: /member-offline/ });
  expect(option).toHaveTextContent("external-group");
  expect(option).toHaveTextContent("10.0.0.4:21000");
  expect(option).toHaveTextContent("离线");
  expect(
    within(select).getByRole("option", { name: /member-online/ }),
  ).toBeDisabled();
  expect(
    within(select).getByRole("option", { name: /member-unknown/ }),
  ).not.toBeDisabled();
  expect(execute).not.toHaveBeenCalled();
  selectMember("member-online");
  expect(submit()).toBeDisabled();
  fireEvent.submit(submit().closest("form")!);
  expect(execute).not.toHaveBeenCalled();
  selectMember("member-offline");
  fireEvent.click(submit());
  await waitFor(() => expect(execute).toHaveBeenCalledOnce());
  expect(execute.mock.calls[0][0].action).toBe("cache.delete");
  expect(execute.mock.calls[0][1]).toEqual({ member_id: "member-offline" });
});

test("missing query requires explicit refresh and switching actions does not repeat it", async () => {
  const execute = vi.fn<Execute>(
    async (_action, _values, _submitted, accepted) => accepted?.(listing()),
  );
  setup(snapshot([]), execute);
  expect(submit()).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "缓存组成员" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "刷新缓存成员列表" }));
  await screen.findByRole("option", { name: /member-offline/ });
  expect(execute).toHaveBeenCalledOnce();
  expect(execute.mock.calls[0][0].action).toBe("cache.list");
  for (const name of ["缓存组与成员列表", "删除缓存组成员登记"]) {
    fireEvent.click(screen.getByRole("button", { name }));
  }
  expect(execute).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("option", { name: /member-offline/ }),
  ).toBeInTheDocument();
});

test("refresh blocks stale selection while pending and after the member disappears", async () => {
  let finish: (() => void) | undefined;
  const execute = vi.fn<Execute>(
    (_action, _values, _submitted, accepted) =>
      new Promise<void>((resolve) => {
        finish = () => {
          accepted?.(
            listing([unknown], {
              id: "list-2",
              created_at: "2026-10-09T02:00:00Z",
            }),
          );
          resolve();
        };
      }),
  );
  setup(snapshot(), execute);
  selectMember("member-offline");
  expect(submit()).not.toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "刷新缓存成员列表" }));
  expect(submit()).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "缓存组成员" })).toBeDisabled();
  fireEvent.submit(submit().closest("form")!);
  expect(execute).toHaveBeenCalledOnce();
  await act(async () => finish?.());
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
  expect(submit()).toBeDisabled();
  fireEvent.submit(submit().closest("form")!);
  expect(execute).toHaveBeenCalledOnce();
});

test("latest failed query never falls back to older successful members", () => {
  setup(
    snapshot([
      listing([], {
        id: "failed",
        state: "failed",
        message: "查询连接失败",
        created_at: "2026-10-09T02:00:00Z",
      }),
      listing(),
    ]),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("查询连接失败");
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
  expect(submit()).toBeDisabled();
});

test("failed explicit refresh invalidates previously usable results", async () => {
  const execute = vi.fn<Execute>(
    async (_action, _values, _submitted, accepted) =>
      accepted?.(
        listing([], {
          id: "failed",
          state: "failed",
          message: "刷新失败",
          created_at: "2026-10-09T02:00:00Z",
        }),
      ),
  );
  setup(snapshot(), execute);
  selectMember("member-offline");
  fireEvent.click(screen.getByRole("button", { name: "刷新缓存成员列表" }));
  await screen.findByRole("alert");
  expect(submit()).toBeDisabled();
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
});

test("polled results replace pending queries and remain available outside the recent history window", async () => {
  const pending = listing([], {
    id: "pending",
    state: "needs_password",
    created_at: "2026-10-09T02:00:00Z",
  });
  const { rerender } = setup(snapshot([pending, listing()]));
  expect(submit()).toBeDisabled();
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
  rerender(
    snapshot([
      listing([offline], {
        ...pending,
        state: "succeeded",
        result: listing([offline]).result,
      }),
    ]),
  );
  await screen.findByRole("option", { name: /member-offline/ });
  rerender(snapshot([]));
  expect(
    screen.getByRole("option", { name: /member-offline/ }),
  ).toBeInTheDocument();
});

test("a newer successful query wins over older errors and a malformed result never becomes a text input", () => {
  const { rerender } = setup(
    snapshot([
      listing([offline], { id: "new", created_at: "2026-10-09T03:00:00Z" }),
      listing([], { state: "failed" }),
    ]),
  );
  selectMember("member-offline");
  expect(submit()).not.toBeDisabled();
  rerender(
    snapshot([
      listing([], {
        id: "malformed",
        created_at: "2026-10-09T04:00:00Z",
        result: { steps: [{ data: {} }] },
      }),
    ]),
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(submit()).toBeDisabled();
  expect(screen.queryByRole("textbox", { name: "缓存组成员" })).toBeNull();
});

test("managed-group delete targets members; offline member stop is disabled", () => {
  const next = snapshot([listing([{ ...offline, group_name: "托管缓存组" }])]);
  next.resources = [
    {
      id: "saved-group",
      kind: "cache",
      name: "托管缓存组",
      state: "running",
      data: { members: [{ member_id: offline.member_id }] },
      created_at: "2026-10-01",
    },
  ];
  const { execute } = setup(next);
  fireEvent.click(screen.getByRole("button", { name: "删除 托管缓存组" }));
  expect(execute.mock.calls[0][0].action).toBe("cache.delete");
  expect(execute.mock.calls[0][1]).toEqual({ member_id: offline.member_id });
  fireEvent.click(screen.getByRole("button", { name: "停止 托管缓存组" }));
  expect(execute).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "停止 托管缓存组" }),
  ).toBeDisabled();
});

test("workspace confirms and posts only the selected external member ID", async () => {
  const stored = snapshot();
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? { id: "deleted", action: "cache.delete", state: "succeeded" }
      : stored,
  );
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <ClusterResources id="cluster-1" name="当前集群" revision={4} canManage />,
  );
  const nav = await screen.findByRole("navigation", { name: "资源功能" });
  fireEvent.click(within(nav).getByRole("button", { name: /缓存组/ }));
  fireEvent.click(screen.getByRole("button", { name: "删除缓存组成员登记" }));
  selectMember("member-offline");
  fireEvent.click(submit());
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0]).toContain("member-offline");
  const calls = vi.mocked(api).mock.calls.filter((call) => call[1] === "POST");
  expect(calls).toHaveLength(2);
  expect(calls[1][2]).toMatchObject({ action: "cache.list" });
  expect(calls[0][2]).toMatchObject({
    action: "cache.delete",
    parameters: { member_id: "member-offline" },
    confirmed: true,
  });
});

test("successful member deletion removes its stale option until a newer query confirms current membership", () => {
  const { rerender, execute } = setup();
  selectMember("member-offline");
  const deleted: ResourceOperation = {
    id: "delete-1",
    action: "cache.delete",
    state: "succeeded",
    payload: { member_id: "member-offline" },
    created_at: "2026-10-09T02:00:00Z",
  };
  rerender(snapshot([deleted, listing()]));
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
  expect(submit()).toBeDisabled();
  fireEvent.submit(submit().closest("form")!);
  expect(execute).not.toHaveBeenCalled();
  rerender(snapshot([]));
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
  rerender(
    snapshot([
      listing([offline], {
        id: "list-new",
        created_at: "2026-10-09T03:00:00Z",
      }),
      deleted,
    ]),
  );
  expect(
    screen.getByRole("option", { name: /member-offline/ }),
  ).toBeInTheDocument();
});

test("failed member deletion preserves the query; rejected refresh still blocks it", async () => {
  const failed: ResourceOperation = {
    id: "delete-1",
    action: "cache.delete",
    state: "failed",
    payload: { member_id: "member-offline" },
    created_at: "2026-10-09T02:00:00Z",
  };
  const execute = vi.fn<Execute>(async () => {
    throw new Error("网络请求失败");
  });
  setup(snapshot([failed, listing()]), execute);
  selectMember("member-offline");
  expect(submit()).not.toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "刷新缓存成员列表" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("网络请求失败");
  expect(submit()).toBeDisabled();
  expect(screen.queryByRole("option", { name: /member-offline/ })).toBeNull();
});

test("group row delete confirms all member IDs, cancellation does not submit", async () => {
  const stored = snapshot([listing([offline, unknown])]);
  stored.catalog.push({
    action: "cache.delete_batch",
    label: "通配符批量删除缓存成员",
    section: "cache",
    mutating: true,
    fields: [
      { key: "member_ids", label: "成员", type: "names", required: true },
    ],
  });
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? { id: "batch", action: "cache.delete_batch", state: "succeeded" }
      : stored,
  );
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(
    <ClusterResources id="cluster-1" name="当前集群" revision={4} canManage />,
  );
  const nav = await screen.findByRole("navigation", { name: "资源功能" });
  fireEvent.click(within(nav).getByRole("button", { name: /缓存组/ }));
  fireEvent.click(screen.getByRole("button", { name: "删除 external-group" }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(confirm.mock.calls[0][0]).toContain("external-group");
  expect(confirm.mock.calls[0][0]).toContain("member-offline");
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(0);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "删除 external-group" }));
  await waitFor(() =>
    expect(
      vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
    ).toHaveLength(1),
  );
  expect(
    vi.mocked(api).mock.calls.find((call) => call[1] === "POST")?.[2],
  ).toMatchObject({
    action: "cache.delete_batch",
    parameters: { member_ids: ["member-offline", "member-unknown"] },
    confirmed: true,
  });
});

test("group row does not silently delete only offline subset", () => {
  const { execute } = setup();
  fireEvent.click(screen.getByRole("button", { name: "删除 external-group" }));
  expect(execute).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("在线");
});
