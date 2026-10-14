import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { CandidateInput } from "./CandidateInput";
function Form({
  label = "Block 大小",
  initial = "4KiB",
  choices = ["4KiB", "1MiB"],
}: {
  label?: string;
  initial?: string;
  choices?: string[];
}) {
  const [value, setValue] = useState(initial);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        throw new Error("unexpected submit");
      }}
    >
      <CandidateInput
        label={label}
        defaultUnit={label === "Block 大小" ? "KiB" : undefined}
        value={value}
        choices={choices}
        onChange={setValue}
      />
      <output data-testid="submitted">{value}</output>
    </form>
  );
}
function selected(label = "Block 大小") {
  return within(screen.getByRole("list", { name: label + "已选值" }))
    .getAllByRole("listitem")
    .map((x) => x.getAttribute("data-value"));
}
test("selected parameters are noneditable tags sorted by actual size and can be removed", () => {
  render(<Form initial="1MiB,4KiB" />);
  expect(screen.queryByRole("textbox", { name: "Block 大小" })).toBeNull();
  expect(selected()).toEqual(["4KiB", "1MiB"]);
  fireEvent.change(screen.getByLabelText("Block 大小自定义值"), {
    target: { value: "64" },
  });
  fireEvent.keyDown(screen.getByLabelText("Block 大小自定义值"), {
    key: "Enter",
  });
  expect(selected()).toEqual(["4KiB", "64KiB", "1MiB"]);
  expect(screen.getByTestId("submitted")).toHaveTextContent(
    "4KiB, 64KiB, 1MiB",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "删除 Block 大小 64KiB" }),
  );
  expect(selected()).toEqual(["4KiB", "1MiB"]);
  expect(screen.getByRole("button", { name: "64KiB" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  fireEvent.click(screen.getByRole("button", { name: "64KiB" }));
  expect(selected()).toEqual(["4KiB", "64KiB", "1MiB"]);
});
test("numbers sort numerically and deleting all tags leaves an empty selection", () => {
  render(<Form label="并发度" initial="16,2" choices={["16", "2", "8"]} />);
  fireEvent.click(screen.getByRole("button", { name: "8" }));
  expect(selected("并发度")).toEqual(["2", "8", "16"]);
  for (const v of ["2", "8", "16"])
    fireEvent.click(screen.getByRole("button", { name: "删除 并发度 " + v }));
  expect(screen.getByTestId("submitted")).toBeEmptyDOMElement();
  expect(screen.getByText("请选择下方参数或添加自定义值")).toBeInTheDocument();
});
test("custom add accepts one value, rejects comma lists and deduplicates equivalent sizes", () => {
  render(<Form initial="1MiB" />);
  const input = screen.getByLabelText("Block 大小自定义值");
  fireEvent.change(input, { target: { value: "8KiB,32KiB" } });
  fireEvent.click(
    screen.getByRole("button", { name: "添加 Block 大小自定义值" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("每次添加一个");
  expect(selected()).toEqual(["1MiB"]);
  fireEvent.change(input, { target: { value: "1024" } });
  fireEvent.click(
    screen.getByRole("button", { name: "添加 Block 大小自定义值" }),
  );
  expect(selected()).toEqual(["1MiB"]);
  expect(input).toHaveValue("");
});

test.each(["B", "KiB", "MiB", "GiB", "TiB", "PiB"])(
  "combines numeric input with selected unit %s",
  (unit) => {
    render(<Form initial="" choices={[]} />);
    fireEvent.change(screen.getByLabelText("Block 大小单位"), {
      target: { value: unit },
    });
    fireEvent.change(screen.getByLabelText("Block 大小自定义值"), {
      target: { value: "2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "添加 Block 大小自定义值" }),
    );
    expect(selected()).toEqual(["2" + unit]);
    expect(screen.getByTestId("submitted")).toHaveTextContent("2" + unit);
  },
);
test("unitless fields have no unit selector and size fields reject typed units", () => {
  const { unmount } = render(
    <Form label="并发度" initial="1" choices={["1"]} />,
  );
  expect(screen.queryByRole("combobox")).toBeNull();
  unmount();
  render(<Form initial="" />);
  fireEvent.change(screen.getByLabelText("Block 大小自定义值"), {
    target: { value: "16k" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "添加 Block 大小自定义值" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("只输入整数");
  expect(screen.getByTestId("submitted")).toBeEmptyDOMElement();
});
