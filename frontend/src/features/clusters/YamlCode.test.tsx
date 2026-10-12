import { render, cleanup } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { YamlCode } from "./YamlCode";
afterEach(cleanup);
test("distinguishes YAML keys, strings, numbers, booleans and comments without changing text", () => {
  const text =
    '# config\nname: "main"\nport: 6900\nenabled: true\nmissing: null\nhost: dingo126\n';
  const { container } = render(<YamlCode text={text} />);
  expect(container.querySelector("code")?.textContent).toBe(text);
  expect(container.querySelector(".key")?.textContent).toBe("name");
  expect(container.querySelector(".string")?.textContent).toBe('"main"');
  expect(container.querySelector(".number")?.textContent).toBe("6900");
  expect(container.querySelector(".boolean")?.textContent).toBe("true");
  expect(container.querySelector(".comment")?.textContent).toBe("# config");
});
test("keeps HTML literal and preserves block scalars and quoted numeric strings", () => {
  const text =
    'value: "123"\nhtml: "<img src=x onerror=alert(1)>"\nscript: |\n  echo true\n  echo 123\n';
  const { container } = render(<YamlCode text={text} />);
  expect(container.querySelector("code")?.textContent).toBe(text);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector(".number")).toBeNull();
});
