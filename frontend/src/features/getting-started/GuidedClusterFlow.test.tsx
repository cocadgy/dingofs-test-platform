import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { DiscoverClusters } from "../clusters/DiscoverClusters";
import { GuidedMachineForm } from "./GuidedMachineForm";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); });

test("created machine can continue to cluster onboarding", async () => {
  const onCreated = vi.fn();
  vi.mocked(api).mockResolvedValue({ id: "new-machine", name: "node-1", address: "10.0.0.1", ssh_port: 22, ssh_user: "jenkins", collection_status: "success" });
  render(<GuidedMachineForm onDirty={vi.fn()} onBack={vi.fn()} onCreated={onCreated} />);
  fireEvent.change(screen.getByLabelText("机器名称"), { target: { value: "node-1" } });
  fireEvent.change(screen.getByLabelText("地址"), { target: { value: "10.0.0.1" } });
  fireEvent.change(screen.getByLabelText("SSH 用户"), { target: { value: "jenkins" } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "检查连接并添加" }));
  fireEvent.click(await screen.findByRole("button", { name: "继续添加集群" }));
  expect(onCreated).toHaveBeenCalledWith("new-machine");
});

test("newly registered machine is preselected for discovery", async () => {
  vi.mocked(api).mockResolvedValue({ items: [{ id: "new-machine", name: "node-1", address: "10.0.0.1", ssh_user: "jenkins", revision: 1, archived: false }], total: 1 });
  const onAddMachine = vi.fn();
  render(<DiscoverClusters initialMachineId="new-machine" onAddMachine={onAddMachine} onImported={vi.fn()} onClose={vi.fn()} admin />);
  await waitFor(() => expect(screen.getByLabelText("执行机器")).toHaveValue("new-machine"));
  expect(screen.getByLabelText("执行用户")).toHaveValue("jenkins");
  fireEvent.click(screen.getByRole("button", { name: "先添加机器" }));
  expect(onAddMachine).toHaveBeenCalledOnce();
});


test("guided discovery confirms selected existing cluster before import", async () => {
  const onImported = vi.fn();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path.startsWith("/machines?")) return { items: [{ id: "machine-1", name: "node-1", address: "10.0.0.1", ssh_user: "jenkins", revision: 1, archived: false }], total: 1 };
    if (path === "/cluster-discoveries" && method === "POST") return { id: "discovery-1", state: "succeeded", result: { names: ["prod-dingo"], registered_names: [] } };
    if (path === "/cluster-discoveries/discovery-1/import" && method === "POST") return { created: [{ id: "cluster-1", name: "prod-dingo" }], existing: [], needs_confirmation: [] };
    return {};
  });
  render(<DiscoverClusters guided onImported={onImported} onClose={vi.fn()} admin />);
  expect(screen.getByRole("region", { name: "发现集群" })).toHaveClass("guided-cluster-discover");
  await screen.findByRole("option", { name: /node-1/ });
  fireEvent.change(screen.getByLabelText("执行机器"), { target: { value: "machine-1" } });
  fireEvent.click(screen.getByRole("button", { name: "查询集群" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "prod-dingo" }));
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText(/将登记：prod-dingo/)).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some((call) => call[0] === "/cluster-discoveries/discovery-1/import")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "确认添加" }));
  await waitFor(() => expect(onImported).toHaveBeenCalledWith(["cluster-1"]));
});
