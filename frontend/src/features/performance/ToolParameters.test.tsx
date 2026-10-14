import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { test, expect } from "vitest";
import { ToolParameters } from "./ToolParameters";
import { defaults, matrixParameters } from "./matrix";
import { Tool } from "./types";
function Form({ tool }: { tool: Tool }) {
  const [s, set] = useState(defaults(tool));
  return (
    <>
      <ToolParameters
        tool={tool}
        s={s}
        sizeMode="files"
        change={(_, key, value) => set((old) => ({ ...old, [key]: value }))}
        onSizeMode={() => {}}
      />
      <output data-testid="ratio">
        {JSON.stringify(matrixParameters(s, "files").read_percent)}
      </output>
    </>
  );
}
test.each(["fio", "elbencho"] as Tool[])(
  "%s mixed ratio defaults to 50 and custom input controls submitted percentage",
  (tool) => {
    render(<Form tool={tool} />);
    expect(screen.queryByText("读 50% / 写 50%")).toBeNull();
    fireEvent.click(screen.getByLabelText(tool + " 顺序混合读写"));
    expect(screen.getByText("读 50% / 写 50%")).toBeInTheDocument();
    expect(screen.getByTestId("ratio")).toHaveTextContent("[50]");
    // Add first to keep a valid ratio while removing the default.
    fireEvent.change(screen.getByLabelText("读比例（%）自定义值"), {
      target: { value: "80" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "添加 读比例（%）自定义值" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "删除 读比例（%） 50" }),
    );
    expect(screen.getByText("读 80% / 写 20%")).toBeInTheDocument();
    expect(screen.getByTestId("ratio")).toHaveTextContent("[80]");
  },
);

test("mdtest exposes metadata controls and submits only supported parameters",()=>{
  render(<Form tool="mdtest"/>);
  expect(screen.getByText("MPI 进程数")).toBeVisible();
  expect(screen.queryByText("Direct I/O（多选）")).toBeNull();
  expect(screen.queryByText("Block 大小")).toBeNull();
  fireEvent.click(screen.getByLabelText("mdtest 共享目录"));
  expect(screen.getByText("预计 2 个组合")).toBeVisible();
  const parameters=matrixParameters({...defaults("mdtest"),layout:["unique","shared"]},"files");
  expect(parameters).toMatchObject({tool:"mdtest",concurrency:[1],file_count:[10000],layout:["unique","shared"]});
  expect(parameters).not.toHaveProperty("block_size");
});
