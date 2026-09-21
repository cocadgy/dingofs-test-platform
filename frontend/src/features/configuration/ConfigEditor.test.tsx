import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { ConfigEditor } from "./ConfigEditor";
afterEach(() => vi.unstubAllGlobals());
function setup(code = 422, admin = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (_url: string, init?: RequestInit) =>
        new Response(
          JSON.stringify(
            init?.method && init.method !== "GET"
              ? { message: code === 409 ? "草稿已更新" : "YAML 格式错误" }
              : _url.endsWith("/versions")
                ? { items: [] }
                : {
                    revision: 1,
                    yaml_text: "# retained\nfilesystem: old\nadvanced: true\n",
                    validation: { syntax_valid: true, tool_validated: false },
                  },
          ),
          {
            status: init?.method && init.method !== "GET" ? code : 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
    ),
  );
  render(
    <ConfigEditor kind="environment" id="e" admin={admin} onDirty={() => {}} />,
  );
}
for (const code of [422, 409])
  it(`retains input on ${code}`, async () => {
    setup(code);
    const input = await screen.findByLabelText("高级 YAML");
    fireEvent.change(input, { target: { value: "filesystem: [" } });
    fireEvent.click(screen.getByText("保存草稿"));
    await screen.findByRole("alert");
    expect(input).toHaveValue("filesystem: [");
    expect(screen.getByText("发布配置版本")).toBeDisabled();
  });
it("member can read but cannot publish", async () => {
  setup(422, false);
  await screen.findByLabelText("高级 YAML");
  expect(screen.queryByText("保存草稿")).not.toBeInTheDocument();
});
it("switching views retains unsaved YAML", async () => {
  setup();
  const input = await screen.findByLabelText("高级 YAML");
  fireEvent.change(input, { target: { value: "# local\nadvanced: true" } });
  fireEvent.click(screen.getByText("常用参数"));
  fireEvent.click(screen.getByText("高级 YAML 编辑"));
  expect(screen.getByLabelText("高级 YAML")).toHaveValue(
    "# local\nadvanced: true",
  );
});
it("shows remote draft without overwriting local conflict text", async () => {
  setup(409);
  const input = await screen.findByLabelText("高级 YAML");
  fireEvent.change(input, { target: { value: "filesystem: local" } });
  fireEvent.click(screen.getByText("保存草稿"));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByText("查看远端版本"));
  await screen.findByLabelText("远端草稿");
  expect(input).toHaveValue("filesystem: local");
});
