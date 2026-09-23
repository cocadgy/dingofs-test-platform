import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, it, expect, vi } from "vitest";
import { MachineHardware } from "./MachineHardware";
afterEach(cleanup);
const snapshot = {
  schema_version: 1,
  cpu: { model: "Example CPU", logical_cores: 8, physical_cores: 4 },
  memory: { total_bytes: 8589934592 },
  disks: [{ name: "sda", type: "disk", size_bytes: 1073741824 }],
  filesystems: [],
  interfaces: [
    {
      name: "eth0",
      mac: "00:11:22:33:44:55",
      addresses: ["10.0.0.1/24"],
      state: "UP",
      mtu: 1500,
      speed_mbps: null,
    },
  ],
  rdma: [],
  warnings: [],
};
const machine = {
  collection_status: "success",
  hardware_info: snapshot,
  last_success_at: "2026-09-23T01:00:00Z",
};
it("普通用户只能查看", () => {
  render(
    <MachineHardware
      machine={machine}
      canEdit={false}
      refreshing={false}
      onRefresh={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: "更新机器信息" })).toBeNull();
  expect(screen.getByText("Example CPU")).toBeTruthy();
  expect(screen.getByText("8.00 GiB")).toBeTruthy();
  expect(screen.getByText("10.0.0.1/24")).toBeTruthy();
});
it("管理员刷新并在请求期间禁用", () => {
  const update = vi.fn();
  const { rerender } = render(
    <MachineHardware
      machine={machine}
      canEdit
      refreshing={false}
      onRefresh={update}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "更新机器信息" }));
  expect(update).toHaveBeenCalledOnce();
  rerender(
    <MachineHardware machine={machine} canEdit refreshing onRefresh={update} />,
  );
  expect(
    (screen.getByRole("button", { name: "采集中…" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
it("失败时继续展示上次成功数据", () => {
  render(
    <MachineHardware
      machine={{
        ...machine,
        collection_status: "failed",
        collection_error: "SSH 认证失败",
      }}
      canEdit
      refreshing={false}
      onRefresh={vi.fn()}
    />,
  );
  expect(screen.getByText("SSH 认证失败")).toBeTruthy();
  expect(screen.getByText("Example CPU")).toBeTruthy();
});
it("部分结果显示缺项和未知速率", () => {
  render(
    <MachineHardware
      machine={{
        collection_status: "partial",
        last_attempt_info: { ...snapshot, warnings: ["cpu: 物理核数未知"] },
      }}
      canEdit
      refreshing={false}
      onRefresh={vi.fn()}
    />,
  );
  expect(screen.getByText("本次部分结果")).toBeTruthy();
  expect(screen.getByText("cpu: 物理核数未知")).toBeTruthy();
  expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
});

it("small capacities are not rounded down to zero GiB", async () => {
  const { bytes } = await import("./MachineHardware");
  expect(bytes(1048576)).toBe("1.00 MiB");
  expect(bytes(0)).toBe("0 B");
});

it("requires explicit fingerprint acknowledgement before trusting", () => {
  const trust = vi.fn();
  const pending = {
    challenge_id: "one",
    host: "node.test",
    port: 22,
    key_type: "ssh-ed25519",
    fingerprint: "SHA256:current",
    previous_fingerprint: null,
    expires_at: new Date(Date.now() + 600000).toISOString(),
  };
  const { rerender } = render(
    <MachineHardware
      machine={{
        collection_status: "needs_trust",
        ssh_host_trust: { pending },
      }}
      canEdit
      refreshing={false}
      onRefresh={vi.fn()}
      onTrust={trust}
    />,
  );
  const button = screen.getByRole("button", { name: "信任并继续" });
  expect(button).toBeDisabled();
  expect(screen.getByText("SHA256:current")).toBeTruthy();
  fireEvent.click(
    screen.getByLabelText("我已通过可信渠道核对该机器的 SSH 指纹"),
  );
  fireEvent.click(button);
  expect(trust).toHaveBeenCalledOnce();
  rerender(
    <MachineHardware
      machine={{
        collection_status: "needs_trust",
        ssh_host_trust: {
          pending: {
            ...pending,
            challenge_id: "two",
            fingerprint: "SHA256:changed",
            previous_fingerprint: "SHA256:current",
          },
        },
      }}
      canEdit
      refreshing={false}
      onRefresh={vi.fn()}
      onTrust={trust}
    />,
  );
  expect(
    screen.getByRole("button", { name: "信任新密钥并继续" }),
  ).toBeDisabled();
  expect(screen.getByText("SHA256:current")).toBeTruthy();
  expect(screen.getByText("SHA256:changed")).toBeTruthy();
});
it("members see the fingerprint but cannot confirm trust", () => {
  render(
    <MachineHardware
      machine={{
        collection_status: "needs_trust",
        ssh_host_trust: {
          pending: {
            challenge_id: "one",
            host: "node",
            port: 22,
            fingerprint: "SHA256:example",
            expires_at: new Date(Date.now() + 600000).toISOString(),
          },
        },
      }}
      canEdit={false}
      refreshing={false}
      onRefresh={vi.fn()}
      onTrust={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: "信任并继续" })).toBeNull();
});
