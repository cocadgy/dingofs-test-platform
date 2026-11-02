import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { GettingStartedPage } from "./GettingStartedPage";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); });

test("chooser opens guided cluster discovery rather than coming soon", () => {
  const onNavigate = vi.fn();
  render(<GettingStartedPage route="chooser" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("想做什么"), { target: { value: "cluster" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/cluster");
});

test("cluster guide can add a machine then return with it selected", async () => {
  const onNavigate = vi.fn();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path.startsWith("/machines?")) return { items: [{ id: "new-machine", name: "node-1", address: "10.0.0.1", ssh_user: "jenkins", revision: 1, archived: false }], total: 1 };
    if (path === "/guided/machines" && method === "POST") return { id: "new-machine", name: "node-1", address: "10.0.0.1", ssh_port: 22, ssh_user: "jenkins", collection_status: "success" };
    return {};
  });
  const view = render(<GettingStartedPage route="cluster" onNavigate={onNavigate} onDirty={vi.fn()} admin />);
  fireEvent.click(await screen.findByRole("button", { name: "先添加机器" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/cluster/machine");
  view.rerender(<GettingStartedPage route="cluster-machine" onNavigate={onNavigate} onDirty={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("机器名称"), { target: { value: "node-1" } });
  fireEvent.change(screen.getByLabelText("地址"), { target: { value: "10.0.0.1" } });
  fireEvent.change(screen.getByLabelText("SSH 用户"), { target: { value: "jenkins" } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "检查连接并添加" }));
  fireEvent.click(await screen.findByRole("button", { name: "继续添加集群" }));
  expect(onNavigate).toHaveBeenCalledWith("#/start/cluster");
  view.rerender(<GettingStartedPage route="cluster" onNavigate={onNavigate} onDirty={vi.fn()} admin />);
  await waitFor(() => expect(screen.getByLabelText("执行机器")).toHaveValue("new-machine"));
  expect(screen.getByLabelText("执行用户")).toHaveValue("jenkins");
});
