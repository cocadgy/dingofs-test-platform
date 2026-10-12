import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterResources } from "./ClusterResources";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
test("automatic list uses normal operation API; delete confirms the selected name", async () => {
  const snapshot = {
    resources: [],
    machines: [],
    operations: [],
    catalog: [
      {
        action: "fs.list",
        label: "文件系统列表",
        section: "filesystem",
        mutating: false,
        fields: [],
      },
      {
        action: "fs.delete",
        label: "删除文件系统",
        section: "filesystem",
        mutating: true,
        fields: [
          {
            key: "fs_name",
            label: "文件系统名称",
            type: "text",
            required: true,
          },
        ],
      },
    ],
  };
  vi.mocked(api).mockImplementation(async (path, method, payload) => {
    if (method !== "POST") return snapshot;
    const action = (payload as { action: string }).action;
    return {
      id: action,
      action,
      state: "succeeded",
      result: {
        steps: [
          { data: { result: { fs_infos: [{ fs_name: "selected-fs" }] } } },
        ],
      },
    };
  });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ClusterResources id="c1" name="测试集群" revision={4} canManage />);
  fireEvent.click(await screen.findByRole("button", { name: "删除文件系统" }));
  await screen.findByRole("option", { name: "selected-fs" });
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("文件系统名称"), {
    target: { value: "selected-fs" },
  });
  fireEvent.click(screen.getByRole("button", { name: "执行删除文件系统" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0]).toContain("selected-fs");
  const posts = vi.mocked(api).mock.calls.filter((call) => call[1] === "POST");
  expect(posts).toHaveLength(2);
  expect(posts[0][2]).toMatchObject({
    action: "fs.list",
    parameters: {},
    confirmed: false,
  });
  expect(posts[1][2]).toMatchObject({
    action: "fs.delete",
    parameters: { fs_name: "selected-fs" },
    confirmed: true,
  });
});
