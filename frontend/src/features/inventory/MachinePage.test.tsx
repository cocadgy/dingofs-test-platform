import {
  render,
  act,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { MachinePage } from "./MachinePage";
const callbacks = vi.hoisted(() => ({
  saved: undefined as undefined | ((id: string) => void),
}));
vi.mock("./InventoryPage", () => ({
  InventoryPage: ({
    initialMachineId,
    onBack,
    onDirty,
    onMachineSaved,
  }: any) => {
    callbacks.saved = onMachineSaved;
    return (
      <div>
        详情 {initialMachineId}
        <button onClick={() => onDirty(true)}>模拟编辑</button>
        <button onClick={onBack}>返回机器概览</button>
      </div>
    );
  },
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});
const item = {
  id: "machine-1",
  name: "node1",
  address: "10.0.0.1",
  ip: "10.0.0.1",
  archived: false,
  collection_status: "never",
  hardware_source: "none",
  cpu_model: null,
  physical_cores: null,
  logical_cores: null,
  memory_bytes: null,
  disk_bytes: null,
  max_speed_mbps: null,
  rdma_devices: null,
  info_updated_at: null,
};
it("row navigation and return preserve filters, sorting and URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ items: [item], total: 1 })),
    ),
  );
  render(<MachinePage admin onDirty={vi.fn()} />);
  await screen.findByRole("button", { name: "node1" });
  fireEvent.change(screen.getByLabelText("搜索资源名"), {
    target: { value: "node" },
  });
  fireEvent.click(screen.getByRole("button", { name: "按总内存排序" }));
  fireEvent.click(screen.getByRole("button", { name: "node1" }));
  await screen.findByText("详情 machine-1");
  expect(window.location.hash).toBe("#/machines/machine-1");
  expect(screen.queryByRole("table")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "返回机器概览" }));
  await screen.findByRole("button", { name: "node1" });
  expect(screen.getByLabelText("搜索资源名")).toHaveValue("node");
  expect(screen.getByRole("columnheader", { name: /总内存/ })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
});
it("supports direct detail URL and protects dirty form on return", async () => {
  window.history.replaceState(null, "", "/#/machines/machine-1");
  vi.stubGlobal(
    "confirm",
    vi.fn(() => false),
  );
  render(<MachinePage admin onDirty={vi.fn()} />);
  expect(screen.getByText("详情 machine-1")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "模拟编辑" }));
  fireEvent.click(screen.getByRole("button", { name: "返回机器概览" }));
  await waitFor(() => expect(window.confirm).toHaveBeenCalledOnce());
  expect(screen.getByText("详情 machine-1")).toBeTruthy();
  expect(window.location.hash).toBe("#/machines/machine-1");
});

it("late save completion cannot navigate away from another module", () => {
  window.history.replaceState(null, "", "/#/machines/new");
  const dirty = vi.fn();
  const { unmount } = render(<MachinePage admin onDirty={dirty} />);
  const saved = callbacks.saved!;
  unmount();
  window.history.replaceState(null, "", "/#/environments");
  dirty.mockClear();
  saved("new-machine");
  expect(window.location.hash).toBe("#/environments");
  expect(dirty).not.toHaveBeenCalled();
});

it("clears stale searches after registration so an uncollected machine is visible", async () => {
  const machines = [item];
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({items: machines, total: machines.length}))));
  render(<MachinePage admin onDirty={vi.fn()} />);
  await screen.findByRole("button", {name: "node1"});
  fireEvent.change(screen.getByLabelText("搜索CPU型号"), {target: {value: "EPYC"}});
  fireEvent.click(screen.getByRole("button", {name: "登记机器资源"}));
  await screen.findByRole("button", {name: "返回机器概览"});
  machines.push({...item, id: "new-machine", name: "new-node"});
  act(() => callbacks.saved!("new-machine"));
  fireEvent.click(screen.getByRole("button", {name: "返回机器概览"}));
  await screen.findByRole("table");
  expect(screen.getByLabelText("搜索CPU型号")).toHaveValue("");
  await screen.findByRole("button", {name: "new-node"});
});
