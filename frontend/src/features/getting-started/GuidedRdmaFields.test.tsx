import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { GuidedRdmaFields, guidedRdmaError } from "./GuidedRdmaFields";
import { blankCacheDraft, newCacheRow } from "./guidedCacheModel";
import type { ResourceMachine } from "../resources/types";
afterEach(cleanup);
const machine: ResourceMachine = { id: "m", name: "node", address: "1.2.3.4", ssh_user: "user", can_manage: true,
  rdma: [{ device: "mlx5_0", port: 1 }, { device: "mlx5_0", port: 2 }, { device: "mlx5_1", port: 3 }] };
function Form() {
  const [row, setRow] = useState({ ...newCacheRow(machine), rdma: true, rdmaDevice: "mlx5_0", rdmaPort: 2 });
  return <GuidedRdmaFields machine={machine} row={row} onChange={patch => setRow({ ...row, ...patch })} />;
}
test("device choices are scoped to the machine and changing device selects its port", () => {
  render(<Form />);
  const devices = screen.getByRole("combobox", { name: "RDMA 设备" });
  expect(within(devices).getAllByRole("option").map(o => o.textContent)).toEqual(["请选择 RDMA 设备", "mlx5_0", "mlx5_1"]);
  fireEvent.change(devices, { target: { value: "mlx5_1" } });
  expect(screen.getByRole("combobox", { name: "RDMA 端口" })).toHaveValue("3");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
test.each([null, []])("missing hardware blocks an enabled row", rdma => {
  const row = { ...newCacheRow(machine), rdma: true, rdmaDevice: "old" };
  render(<GuidedRdmaFields machine={{ ...machine, rdma }} row={row} onChange={() => {}} />);
  expect(screen.getByRole("alert")).toHaveTextContent(rdma === null ? "未采集" : "没有 RDMA");
  expect(guidedRdmaError({ ...blankCacheDraft(), rows: [row] }, [{ ...machine, rdma }])).not.toBe("");
});
test("stale template pair blocks next/submit but valid pair and disabled RDMA pass", () => {
  const row = { ...newCacheRow(machine), rdma: true, rdmaDevice: "mlx5_0", rdmaPort: 3 };
  expect(guidedRdmaError({ ...blankCacheDraft(), rows: [row] }, [machine])).not.toBe("");
  expect(guidedRdmaError({ ...blankCacheDraft(), rows: [{ ...row, rdmaPort: 2 }] }, [machine])).toBe("");
  expect(guidedRdmaError({ ...blankCacheDraft(), rows: [{ ...row, rdma: false }] }, [machine])).toBe("");
});
