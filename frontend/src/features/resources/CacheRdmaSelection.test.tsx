import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ResourceFields } from "./ResourceFields";
import { cacheRdmaReady } from "./cacheRdma";
import type { Parameters, ResourceMachine } from "./types";

afterEach(cleanup);
const machines: ResourceMachine[] = [
  { id: "a", name: "host-a", address: "10.0.0.1", ssh_user: "root", can_manage: true, rdma: [
    { device: "mlx5_bond_0", port: 1 }, { device: "mlx5_bond_0", port: 2 }, { device: "mlx5_1", port: 1 },
  ] },
  { id: "b", name: "host-b", address: "10.0.0.2", ssh_user: "root", can_manage: true, rdma: [{ device: "mlx5_0", port: 1 }] },
  { id: "none", name: "host-none", address: "10.0.0.3", ssh_user: "root", can_manage: true, rdma: [] },
  { id: "unknown", name: "host-unknown", address: "10.0.0.4", ssh_user: "root", can_manage: true, rdma: null },
];
const action = { action: "cache.create", label: "创建缓存组", section: "cache" as const, mutating: true, fields: [
  { key: "members", label: "缓存成员", type: "members" as const },
] };
function Form() {
  const [values, setValues] = useState<Parameters>({ members: [{ machine_id: "a", use_rdma: false, rdma_device: "", rdma_port: 1 }] });
  return <ResourceFields action={action} values={values} machines={machines} resources={[]} disabled={false}
    onChange={(key, value) => setValues(previous => ({ ...previous, [key]: value }))} />;
}

test("RDMA choices come from the selected machine and ports follow the device", () => {
  render(<Form />);
  fireEvent.click(screen.getByRole("checkbox", { name: "成员 1 使用 RDMA" }));
  expect(screen.getByRole("combobox", { name: "成员 1 RDMA 设备" })).toHaveValue("mlx5_bond_0");
  expect(screen.getByRole("combobox", { name: "成员 1 RDMA 端口" })).toHaveValue("1");
  expect(screen.getByRole("option", { name: "2" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "成员 1 RDMA 端口" }), { target: { value: "2" } });
  fireEvent.change(screen.getByRole("combobox", { name: "成员 1 RDMA 设备" }), { target: { value: "mlx5_1" } });
  expect(screen.getByRole("combobox", { name: "成员 1 RDMA 端口" })).toHaveValue("1");
  fireEvent.change(screen.getByRole("combobox", { name: "成员 1 机器" }), { target: { value: "b" } });
  expect(screen.getByRole("combobox", { name: "成员 1 RDMA 设备" })).toHaveValue("mlx5_0");
});

test("missing or uncollected RDMA hardware shows a clear error", () => {
  render(<Form />);
  fireEvent.change(screen.getByRole("combobox", { name: "成员 1 机器" }), { target: { value: "none" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "成员 1 使用 RDMA" }));
  expect(screen.getByRole("alert")).toHaveTextContent("没有 RDMA 设备");
  expect(cacheRdmaReady([{ machine_id: "none", use_rdma: true, rdma_device: "", rdma_port: 1 }], machines)).toBe(false);
  fireEvent.change(screen.getByRole("combobox", { name: "成员 1 机器" }), { target: { value: "unknown" } });
  expect(screen.getByRole("alert")).toHaveTextContent("未采集 RDMA 信息");
});

test("stale profile RDMA pair cannot be submitted", () => {
  expect(cacheRdmaReady([{ machine_id: "a", use_rdma: true, rdma_device: "mlx5_0", rdma_port: 1 }], machines)).toBe(false);
  expect(cacheRdmaReady([{ machine_id: "a", use_rdma: true, rdma_device: "mlx5_bond_0", rdma_port: 2 }], machines)).toBe(true);
});
