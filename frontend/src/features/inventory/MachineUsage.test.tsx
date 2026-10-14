import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MachineUsage } from "./MachineUsage";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const current = new Date().toISOString();
test("machine detail shows CPU, memory and each disk usage from the live dashboard probe", async () => {
  vi.mocked(api).mockResolvedValue({ machines: [{ id: "m1", probe: { state: "healthy", error: null, checked_at: current,
    usage: { cpu_percent: 25, memory_used_bytes: 50, memory_total_bytes: 100,
      disks: [{ mountpoint: "/", device: "/dev/mapper/rl-root", used_bytes: 97, total_bytes: 100, percent: 97 }] } } }] });
  render(<MachineUsage machineId="m1" />);
  expect(await screen.findByText("CPU 占用率")).toBeInTheDocument();
  expect(screen.getByText("内存占用率")).toBeInTheDocument();
  expect(screen.getAllByText("磁盘占用率")).toHaveLength(2);
  expect(screen.getByText("/dev/mapper/rl-root")).toBeInTheDocument();
  expect(screen.getAllByText("97%")).toHaveLength(2);
  expect(screen.getByText("需关注")).toBeInTheDocument();
});
test("machine detail does not present stale usage as current", async () => {
  vi.mocked(api).mockResolvedValue({ machines: [{ id: "m1", probe: { state: "healthy", error: null,
    checked_at: "2020-01-01T00:00:00Z", usage: { cpu_percent: 99, memory_used_bytes: 99, memory_total_bytes: 100, disks: [] } } }] });
  render(<MachineUsage machineId="m1" />);
  expect(await screen.findByText(/占用率数据已过期/)).toBeInTheDocument();
  expect(screen.queryByText("99%")).not.toBeInTheDocument();
});
