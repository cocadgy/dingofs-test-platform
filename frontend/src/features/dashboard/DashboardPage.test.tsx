import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { DashboardPage } from "./DashboardPage";
import type { Dashboard } from "./health";
import { api } from "../../api/client";
vi.mock("../../api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const current = new Date().toISOString();
const snapshot: Dashboard = {
  generated_at: current, progress: { running: false, completed: 2, total: 2 },
  machines: [{ id: "m1", name: "node-1", address: "10.0.0.1", ip: "10.0.0.1", archived: false,
    creator_id: "u1", maintenance: false, collection_status: "success", cpu_model: "Intel",
    physical_cores: 8, logical_cores: 16, memory_bytes: 17179869184, disk_bytes: 107374182400,
    max_speed_mbps: 25000, rdma_devices: ["mlx5_0"], info_updated_at: current,
    cluster_ids: ["c1"], probe: { state: "warning", error: "authentication_failed", checked_at: current } }],
  clusters: [{ id: "c1", name: "daily", external_name: "main-dingofs", creator_id: "u1",
    archived: false, binding_state: "verified", management_machine_id: "m1",
    machine_name: "node-1", os_user: "jenkins", state: "degraded", last_success_at: current,
    last_attempt_at: current, last_error: null, service_count: 3, running_instances: 2,
    expected_instances: 3, roles: { mds: { running: 2, expected: 3 } }, services: [] }],
};
test("home surfaces actionable failures, links and filters", async () => {
  vi.mocked(api).mockResolvedValue(snapshot);
  render(<DashboardPage userId="u1" />);
  expect(await screen.findByRole("heading", { name: "资源总览" })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "资源管理" })).toHaveAttribute("href", "#/clusters/c1/resources");
  expect(screen.getAllByText("SSH 认证失败")).toHaveLength(2);
  expect(screen.getByText("mds 2/3")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "node-1" })[0]).toHaveAttribute("href", "#/machines/m1");
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索资源" }), { target: { value: "missing" } });
  expect(screen.getByText("没有符合筛选条件的集群。")).toBeInTheDocument();
  expect(screen.getByText("没有符合筛选条件的机器。")).toBeInTheDocument();
});

test("machine row shows live usage and expandable disk details", async () => {
  const usage = { cpu_percent: 25, memory_used_bytes: 8589934592, memory_total_bytes: 17179869184,
    disks: [{ mountpoint: "/mnt/disk1", mountpoints: ["/mnt/disk1", "/mnt/archive"], device: "/dev/nvme0n1", used_bytes: 950,
      total_bytes: 1000, percent: 95 }] };
  vi.mocked(api).mockResolvedValue({ ...snapshot, clusters: [], machines: [{ ...snapshot.machines[0],
    probe: { state: "healthy", error: null, checked_at: current, usage, usage_error: null } }] });
  render(<DashboardPage userId="u1" />);
  expect(await screen.findByText("CPU 占用率")).toBeInTheDocument();
  expect(screen.getByText("25%")).toBeInTheDocument();
  expect(screen.getByText("95%")).toBeInTheDocument();
  expect(screen.getByText(/磁盘空间不足/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看 node-1 的磁盘明细" }));
  expect(screen.getByText("/dev/nvme0n1")).toBeInTheDocument();
  expect(screen.getByText("/mnt/archive")).toBeInTheDocument();
});
