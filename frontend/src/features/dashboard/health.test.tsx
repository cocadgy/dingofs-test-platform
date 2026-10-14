import { expect, test } from "vitest";
import { clusterHealth, machineHealth, type Cluster, type Machine } from "./health";
const now = Date.parse("2026-10-12T10:00:00Z");
const machine = {
  id: "m1", name: "node", address: "10.0.0.1", ip: "10.0.0.1", archived: false,
  creator_id: "u", maintenance: false, collection_status: "success", cpu_model: null,
  physical_cores: null, logical_cores: null, memory_bytes: null, disk_bytes: null,
  max_speed_mbps: null, rdma_devices: null, info_updated_at: null, cluster_ids: [],
  probe: null,
} satisfies Machine;
const cluster = {
  id: "c1", name: "cluster", external_name: "cluster", creator_id: "u",
  archived: false, binding_state: "verified", management_machine_id: "m1",
  machine_name: "node", os_user: "root", state: "running",
  last_success_at: "2026-10-12T09:59:00Z", last_attempt_at: "2026-10-12T09:59:00Z",
  last_error: null, service_count: 3, running_instances: 3, expected_instances: 3,
  roles: {}, services: [],
} satisfies Cluster;
test("historical hardware collection does not imply current SSH availability", () => {
  expect(machineHealth(machine, now)).toBe("unknown");
  expect(machineHealth({ ...machine, probe: { state: "healthy", error: null, checked_at: "2026-10-12T09:59:00Z" } }, now)).toBe("healthy");
  expect(machineHealth({ ...machine, probe: { state: "warning", error: "authentication_failed", checked_at: "2026-10-12T09:59:00Z" } }, now)).toBe("warning");
  expect(machineHealth({ ...machine, probe: { state: "warning", error: "connection_failed", checked_at: "2026-10-12T09:59:00Z" } }, now)).toBe("critical");
});
test("a failed or stale cluster probe cannot inherit an old green snapshot", () => {
  expect(clusterHealth(cluster, now)).toBe("healthy");
  expect(clusterHealth({ ...cluster, last_error: "query_failed" }, now)).toBe("warning");
  expect(clusterHealth({ ...cluster, last_error: "needs_password" }, now)).toBe("warning");
  expect(clusterHealth({ ...cluster, last_error: "pending" }, now)).toBe("unknown");
  expect(clusterHealth({ ...cluster, last_attempt_at: "2026-10-12T09:50:00Z" }, now)).toBe("unknown");
  expect(clusterHealth({ ...cluster, state: "degraded" }, now)).toBe("critical");
});

test("a single full local disk requires attention only while telemetry is fresh", () => {
  const usage = { cpu_percent: 22, memory_used_bytes: 300, memory_total_bytes: 1000,
    disks: [{ mountpoint: "/mnt/disk1", device: "/dev/nvme0n1", used_bytes: 910,
      total_bytes: 1000, percent: 91 }] };
  const loaded = { ...machine, probe: { state: "healthy", error: null,
    checked_at: "2026-10-12T09:59:00Z", usage, usage_error: null } } satisfies Machine;
  expect(machineHealth(loaded, now)).toBe("warning");
  expect(machineHealth({ ...loaded, probe: { ...loaded.probe, checked_at: "2026-10-12T09:50:00Z" } }, now)).toBe("unknown");
  expect(machineHealth({ ...loaded, probe: { ...loaded.probe, usage: { ...usage,
    disks: [{ ...usage.disks[0], used_bytes: 900, percent: 90 }] } } }, now)).toBe("healthy");
  expect(machineHealth({ ...loaded, probe: { ...loaded.probe, usage: { ...usage,
    disks: [{ ...usage.disks[0], used_bytes: 900001, total_bytes: 1000000, percent: 90 }] } } }, now)).toBe("warning");
});
