import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { GettingStartedPage } from "./GettingStartedPage";

afterEach(cleanup);

test("lists seven guided actions and opens machine onboarding", () => {
  const navigate = vi.fn();
  render(<GettingStartedPage route="chooser" onNavigate={navigate} onDirty={vi.fn()} />);
  const select = screen.getByLabelText("想做什么") as HTMLSelectElement;
  expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
    "添加机器", "添加集群", "创建文件系统", "创建缓存组", "挂载文件系统", "功能测试", "性能测试",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(navigate).toHaveBeenCalledWith("#/start/machine");
});

test("future actions have an explicit coming-soon state", () => {
  render(<GettingStartedPage route="chooser" onNavigate={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("想做什么"), { target: { value: "cache" } });
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByText("即将支持")).toBeInTheDocument();
});
