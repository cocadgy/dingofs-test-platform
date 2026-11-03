import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { CapacityInput, type CapacityUnit } from "./CapacityInput";
afterEach(cleanup);
function Form() {
  const [value, setValue] = useState(1024);
  const [unit, setUnit] = useState<CapacityUnit>("MiB");
  return <><CapacityInput value={value} unit={unit} onChange={setValue} onUnitChange={setUnit} /><output>{value}</output></>;
}
test("unit changes preserve canonical MiB and fractional GiB edits convert", () => {
  render(<Form />);
  fireEvent.change(screen.getByLabelText("容量单位"), { target: { value: "GiB" } });
  expect(screen.getByLabelText("每节点容量")).toHaveValue(1);
  expect(screen.getByRole("status")).toHaveTextContent("1024");
  fireEvent.change(screen.getByLabelText("容量单位"), { target: { value: "TiB" } });
  expect(screen.getByLabelText("每节点容量")).toHaveValue(0.0009765625);
  fireEvent.change(screen.getByLabelText("容量单位"), { target: { value: "GiB" } });
  fireEvent.change(screen.getByLabelText("每节点容量"), { target: { value: "1.5" } });
  expect(screen.getByRole("status")).toHaveTextContent("1536");
});
