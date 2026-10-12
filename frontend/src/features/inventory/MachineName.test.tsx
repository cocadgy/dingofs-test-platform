import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { InventoryPage } from "./InventoryPage";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("documents Chinese display names and submits Chinese without changing SSH fields", async () => {
  let saved: Record<string, unknown> | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      saved = JSON.parse(options.body);
      return new Response(
        JSON.stringify({ ...saved, id: "m1", revision: 1, archived: false }),
      );
    }),
  );
  render(
    <InventoryPage
      kind="machines"
      admin
      detailOnly
      createMachine
      onDirty={vi.fn()}
    />,
  );
  expect(screen.getByText(/支持中文.*120/)).toBeInTheDocument();
  const name = screen.getByLabelText("名称");
  fireEvent.change(name, { target: { value: "北京测试机器（NVMe）01" } });
  fireEvent.change(screen.getByLabelText("主机地址"), {
    target: { value: "192.0.2.10" },
  });
  fireEvent.change(screen.getByLabelText("SSH 用户"), {
    target: { value: "jenkins" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存资源" }));
  await waitFor(() => expect(saved?.name).toBe("北京测试机器（NVMe）01"));
  expect(saved?.address).toBe("192.0.2.10");
  expect(saved?.ssh_user).toBe("jenkins");
  expect(name).toHaveAttribute("maxlength", "120");
});
