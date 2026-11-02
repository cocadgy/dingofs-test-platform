import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GuidedMachineForm } from "./GuidedMachineForm";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); });

function fill() {
  fireEvent.change(screen.getByLabelText("机器名称"), { target: { value: "node-1" } });
  fireEvent.change(screen.getByLabelText("地址"), { target: { value: "10.0.0.1" } });
  fireEvent.change(screen.getByLabelText("SSH 用户"), { target: { value: "jenkins" } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "  keep me  " } });
}

test("submits exactly five fields preserving password whitespace", async () => {
  vi.mocked(api).mockResolvedValue({ id: "machine-1", name: "node-1", address: "10.0.0.1", ssh_port: 22, ssh_user: "jenkins", collection_status: "success", hardware_info: { cpu: { logical_cores: 8 } } });
  render(<GuidedMachineForm onDirty={vi.fn()} onBack={vi.fn()} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "检查连接并添加" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/guided/machines", "POST", { name: "node-1", address: "10.0.0.1", ssh_port: 22, ssh_user: "jenkins", ssh_password: "  keep me  " }));
  expect(await screen.findByText("机器添加成功")).toBeInTheDocument();
  expect(screen.getByText("8")).toBeInTheDocument();
  expect(screen.queryByText("  keep me  ")).not.toBeInTheDocument();
});

test("connection failure keeps nonsecret fields and clears password", async () => {
  vi.mocked(api).mockRejectedValue(new Error("SSH 认证失败"));
  render(<GuidedMachineForm onDirty={vi.fn()} onBack={vi.fn()} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "检查连接并添加" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("SSH 认证失败");
  expect(screen.getByLabelText("机器名称")).toHaveValue("node-1");
  expect(screen.getByLabelText("SSH 密码")).toHaveValue("");
});
