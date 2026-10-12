import { render, screen, within, cleanup } from "@testing-library/react";
import { afterEach, test, expect, vi } from "vitest";
import { ResourceSectionForm } from "./ResourceSectionForm";
import { sections } from "./workspace";
afterEach(cleanup);
test("submission errors remain visible beside the execution button", () => {
  render(
    <ResourceSectionForm
      section={sections[1]}
      snapshot={{
        catalog: [
          {
            action: "cache.create",
            label: "创建缓存组",
            section: "cache",
            mutating: true,
            fields: [],
          },
        ],
        operations: [],
        resources: [],
        machines: [],
      }}
      disabled={false}
      execute={vi.fn()}
      group="缓存组操作"
      onGroupChange={vi.fn()}
      submissionError="监听端口必须在 1–65535 之间"
    />,
  );
  const form = screen
    .getByRole("button", { name: "执行创建缓存组" })
    .closest("form")!;
  expect(within(form).getByRole("alert")).toHaveTextContent("监听端口");
});
