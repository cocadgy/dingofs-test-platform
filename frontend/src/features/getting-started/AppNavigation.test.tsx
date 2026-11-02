import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../../App";
import { api } from "../../api/client";

vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); window.history.replaceState(null, "", "#/"); });

function session() {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/auth/me") return { id: "u1", username: "tester", email: "tester@example.com", role: "member", csrf_token: "token" };
    if (path === "/dashboard") return { generated_at: new Date().toISOString(), progress: { running: false, completed: 0, total: 0 }, machines: [], clusters: [] };
    return {};
  });
}

test("start navigation precedes resource overview and opens the chooser", async () => {
  window.history.replaceState(null, "", "#/start");
  session();
  render(<App />);
  expect(await screen.findByRole("heading", { name: "开始" })).toBeInTheDocument();
  const nav = screen.getByRole("navigation");
  const labels = Array.from(nav.querySelectorAll("button")).map((button) => button.textContent);
  expect(labels[0]).toContain("开始");
  expect(labels[1]).toContain("资源总览");
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  await waitFor(() => expect(window.location.hash).toBe("#/start/machine"));
  expect(await screen.findByRole("heading", { name: "添加机器" })).toBeInTheDocument();
});

test("session expiry removes the form and its password", async () => {
  window.history.replaceState(null, "", "#/start/machine");
  session();
  render(<App />);
  fireEvent.change(await screen.findByLabelText("SSH 密码"), { target: { value: "temporary-secret" } });
  window.dispatchEvent(new Event("session-expired"));
  await waitFor(() => expect(screen.queryByLabelText("SSH 密码")).not.toBeInTheDocument());
  expect(screen.queryByText("temporary-secret")).not.toBeInTheDocument();
});


test("leaving the start guide through the sidebar requires confirmation even before editing", async () => {
  window.history.replaceState(null, "", "#/start");
  session();
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<App />);
  expect(await screen.findByRole("heading", { name: "开始" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /资源总览/ }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(window.location.hash).toBe("#/start");
  expect(screen.getByRole("heading", { name: "开始" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /资源总览/ }));
  expect(confirm).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(window.location.hash).toBe("#/dashboard"));
});

test("leaving a partly filled machine guide through the sidebar warns about unsaved input", async () => {
  window.history.replaceState(null, "", "#/start/machine");
  session();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<App />);
  fireEvent.change(await screen.findByLabelText("机器名称"), { target: { value: "draft-node" } });
  fireEvent.click(screen.getByRole("button", { name: /资源总览/ }));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("未保存"));
  expect(window.location.hash).toBe("#/start/machine");
  expect(screen.getByLabelText("机器名称")).toHaveValue("draft-node");
});
