import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
  cleanup,
} from "@testing-library/react";
import { afterEach, it, expect, vi } from "vitest";
import { useState } from "react";
import {
  MachineOverview,
  initialTableState,
  columns,
  filterAndSort,
  formatCell,
  type OverviewRow,
} from "./MachineOverview";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function row(name: string, n: number | null): OverviewRow {
  return {
    id: name,
    name,
    address: "node.test",
    ip: `10.0.0.${n ?? 99}`,
    archived: false,
    collection_status: "success",
    hardware_source: "complete",
    cpu_model: "Example CPU",
    physical_cores: n,
    logical_cores: n,
    memory_bytes: n == null ? null : n * 1024 ** 3,
    disk_bytes: 1024 ** 4,
    max_speed_mbps: n == null ? null : n * 1000,
    rdma_devices: ["mlx5_0"],
    info_updated_at: "2026-09-23T01:00:00Z",
  };
}
it("all ten columns have searchable display values and numeric sorting keeps missing last", () => {
  expect(columns.map((c) => c.label)).toEqual([
    "资源名",
    "IP",
    "CPU型号",
    "物理CPU核数",
    "逻辑CPU核数",
    "总内存",
    "总磁盘",
    "网卡速率（最大）",
    "RDMA设备",
    "信息更新时间",
  ]);
  const rows = [
    row("node128", 128),
    row("unknown", null),
    row("node2", 2),
    row("node16", 16),
  ];
  for (const field of [
    "physical_cores",
    "logical_cores",
    "memory_bytes",
    "disk_bytes",
    "max_speed_mbps",
    "info_updated_at",
  ] as const) {
    const sorted = filterAndSort(rows, {
      ...initialTableState,
      sortBy: field,
      sortDir: "asc",
    });
    if (field !== "disk_bytes" && field !== "info_updated_at")
      expect(sorted.map((r) => r.name)).toEqual([
        "node2",
        "node16",
        "node128",
        "unknown",
      ]);
  }
  expect(
    filterAndSort(rows, {
      ...initialTableState,
      sortBy: "memory_bytes",
      sortDir: "desc",
    }).map((r) => r.name),
  ).toEqual(["node128", "node16", "node2", "unknown"]);
  for (const c of columns) {
    const term = formatCell(rows[0], c.key);
    expect(
      filterAndSort(rows, {
        ...initialTableState,
        filters: { [c.key]: term },
      }).some((r) => r.name === "node128"),
    ).toBe(true);
  }
  expect(
    filterAndSort(rows, {
      ...initialTableState,
      filters: { name: "node", memory_bytes: "16.00", rdma_devices: "MLX5" },
    }).map((r) => r.name),
  ).toEqual(["node16"]);
});
it("fetches all pages before filtering, opens a machine, and toggles each sort header", async () => {
  const rows = Array.from({ length: 25 }, (_, i) =>
    row("node" + String(i).padStart(2, "0"), i + 1),
  );
  const fetch = vi.fn(
    async (input: RequestInfo | URL) =>
      new Response(
        JSON.stringify({
          total: 25,
          items: String(input).includes("offset=20")
            ? rows.slice(20)
            : rows.slice(0, 20),
        }),
      ),
  );
  vi.stubGlobal("fetch", fetch);
  const open = vi.fn();
  function Harness() {
    const [state, setState] = useState(initialTableState);
    return (
      <MachineOverview state={state} onStateChange={setState} onOpen={open} />
    );
  }
  render(<Harness />);
  await screen.findByRole("button", { name: "node00" });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getAllByRole("searchbox")).toHaveLength(10);
  fireEvent.change(screen.getByLabelText("搜索资源名"), {
    target: { value: "node24" },
  });
  await screen.findByRole("button", { name: "node24" });
  expect(screen.queryByRole("button", { name: "node00" })).toBeNull();
  fireEvent.click(screen.getByRole("cell", { name: "10.0.0.25" }));
  expect(open).toHaveBeenCalledWith("node24");
  fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(screen.getByRole("button", { name: "node24" })).toBeTruthy();
  for (const c of columns) {
    fireEvent.click(screen.getByRole("button", { name: `按${c.label}排序` }));
    const header = screen.getByRole("columnheader", {
      name: new RegExp(c.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    });
    expect(header.getAttribute("aria-sort")).toMatch(/ascending|descending/);
  }
});
it("does not show partial inventory as a complete result if a later page fails", async () => {
  let n = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      ++n === 1
        ? new Response(JSON.stringify({ items: [row("node", 1)], total: 2 }))
        : new Response(JSON.stringify({ message: "读取失败" }), {
            status: 500,
          }),
    ),
  );
  render(
    <MachineOverview
      state={initialTableState}
      onStateChange={vi.fn()}
      onOpen={vi.fn()}
    />,
  );
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "node" })).toBeNull();
});

it("shows uncollected machines with empty hardware cells and allows opening details", async () => {
  const machine: OverviewRow = {
    ...row("new-node", null), collection_status: "never", hardware_source: "none",
    cpu_model: null, disk_bytes: null, rdma_devices: null, info_updated_at: null,
  };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({items: [machine], total: 1}))));
  const open = vi.fn();
  render(<MachineOverview state={initialTableState} onStateChange={vi.fn()} onOpen={open} />);
  const name = await screen.findByRole("button", {name: "new-node"});
  const cells = within(name.closest("tr")!).getAllByRole("cell");
  expect(cells).toHaveLength(10);
  expect(cells[1]).toHaveTextContent("10.0.0.99");
  for (const cell of cells.slice(2)) expect(cell.textContent).toBe("");
  fireEvent.click(name);
  expect(open).toHaveBeenCalledWith("new-node");
});
