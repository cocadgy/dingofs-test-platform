import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { ClusterDetail } from "./ClusterDetail";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("./ClusterTopology", () => ({ ClusterTopology: () => null }));
vi.mock("./ClusterControl", () => ({ ClusterControl: () => null }));
const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  navigator,
  "clipboard",
);
const commandDescriptor = Object.getOwnPropertyDescriptor(
  document,
  "execCommand",
);
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (clipboardDescriptor)
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else Reflect.deleteProperty(navigator, "clipboard");
  if (commandDescriptor)
    Object.defineProperty(document, "execCommand", commandDescriptor);
  else Reflect.deleteProperty(document, "execCommand");
});

async function directory(label = "日志目录") {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/remote-targets")) return { items: [], services: [] };
    return {
      id: "c1",
      name: "测试集群",
      external_name: "main-dingofs",
      revision: 1,
      creator_id: "owner",
      archived: false,
      binding_state: "verified",
      status_snapshot: {
        services: [
          {
            id: "mds1",
            role: "mds",
            host: "node-one",
            ports: [6900],
            state: "running",
            running_instances: 1,
            expected_instances: 1,
            status_text: "Up 1 day",
            log_dir: "/home/operator/dingofs/logs/mds0",
            data_dir: "/srv/dingofs/data",
            raft_dir: "/srv/dingofs/raft",
          },
        ],
      },
    };
  });
  render(
    <ClusterDetail
      id="c1"
      admin={false}
      userId="viewer"
      onBack={() => {}}
      onDirty={() => {}}
      onDiscover={() => {}}
    />,
  );
  fireEvent.click(await screen.findByText("查看目录"));
  return within(
    screen
      .getByText(label, { selector: "strong" })
      .closest(".cluster-directory") as HTMLElement,
  );
}

test("HTTP clipboard fallback copies the selected log path and reports success next to its button", async () => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });
  const written: string[] = [];
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => {
      const input = document.activeElement as HTMLTextAreaElement;
      written.push(input.value.slice(input.selectionStart, input.selectionEnd));
      return true;
    }),
  });
  const ui = await directory();
  fireEvent.click(ui.getByRole("button", { name: "复制路径" }));
  await waitFor(() =>
    expect(written).toEqual(["/home/operator/dingofs/logs/mds0"]),
  );
  expect(await ui.findByRole("status")).toHaveTextContent("已复制");
  expect(document.querySelector(".clipboard-copy-buffer")).toBeNull();
});

test("clipboard rejection is visible beside the path instead of silently claiming success", async () => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => false),
  });
  const ui = await directory();
  fireEvent.click(ui.getByRole("button", { name: "复制路径" }));
  expect(await ui.findByRole("status")).toHaveTextContent("复制失败");
  expect(ui.getByRole("status")).not.toHaveTextContent("已复制");
});

test("modern clipboard copy shows feedback only at the clicked directory", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const ui = await directory("数据目录");
  fireEvent.click(ui.getByRole("button", { name: "复制路径" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith("/srv/dingofs/data"),
  );
  expect(await ui.findByRole("status")).toHaveTextContent("已复制");
  const logDirectory = screen
    .getByText("日志目录", { selector: "strong" })
    .closest(".cluster-directory") as HTMLElement;
  expect(within(logDirectory).queryByRole("status")).toBeNull();
});
