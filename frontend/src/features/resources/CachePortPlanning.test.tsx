import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
import type { ResourceSnapshot } from "./types";
import type { Execute } from "./useResourceWorkspace";
afterEach(cleanup);
test.each(["succeeded", "failed", "running"])("port check %s only auto-creates on success", async (state) => {
  const catalog: ResourceSnapshot["catalog"] = [
    {
      action: "cache.create",
      label: "创建缓存组",
      section: "cache",
      mutating: true,
      fields: [
        {
          key: "group_name",
          label: "缓存组名称",
          type: "text",
          required: true,
        },
      ],
    },
    {
      action: "cache.plan",
      label: "检查缓存成员端口",
      section: "cache",
      mutating: false,
      fields: [],
    },
  ];
  const execute = vi.fn<Execute>(async (action, _p, _s, accepted) => {
    if (action.action === "cache.plan")
      accepted?.({
        id: "plan-1",
        action: "cache.plan",
        state,
        result: {
          steps: [
            {
              data: {
                effective_port: 21003,
                member: {
                  machine_id: "m",
                  target_user: "jenkins",
                  listen_ip: "192.0.2.1",
                  listen_port: 21003,
                  cache_dir: "/cache/uuid",
                  cache_size_mb: 1024,
                },
              },
            },
          ],
        },
      });
  });
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={{ catalog, resources: [], machines: [], operations: [] }}
      disabled={false}
      execute={execute}
      group="缓存组操作"
      onGroupChange={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("缓存组名称"), {
    target: { value: "g" },
  });
  fireEvent.click(screen.getByRole("button", { name: "检查并创建缓存组" }));
  if (state !== "succeeded") {
    await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
    expect(execute).toHaveBeenCalledTimes(1);
    expect(execute.mock.calls[0][0].action).toBe("cache.plan");
    return;
  }
  await waitFor(() =>
    expect(
      screen.getByRole("table", { name: "缓存成员端口检查清单" }),
    ).toBeVisible(),
  );
  expect(screen.getByText("21003")).toBeVisible();
  expect(execute.mock.calls[0][0].action).toBe("cache.plan");
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2));
  expect(execute.mock.calls[1][4]).toEqual({ autoCreateFromPlan: true });
  expect(execute.mock.calls[1][0].action).toBe("cache.create");
  expect(execute.mock.calls[1][1]).toEqual({ plan_id: "plan-1" });
  fireEvent.change(screen.getByLabelText("缓存组名称"), {
    target: { value: "changed" },
  });
  expect(
    screen.queryByRole("table", { name: "缓存成员端口检查清单" }),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: "检查并创建缓存组" }),
  ).toBeVisible();
});
