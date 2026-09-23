import { render, screen, fireEvent } from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { ProfilePage } from "./ProfilePage";
afterEach(() => vi.unstubAllGlobals());
it("sends current password and keeps email on verification failure", async () => {
  const fetch = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ message: "当前密码不正确，修改未保存" }), {
        status: 403,
      }),
  );
  vi.stubGlobal("fetch", fetch);
  render(
    <ProfilePage
      email="old@example.com"
      onEmailSaved={() => {}}
      onPasswordChanged={() => {}}
      onDirty={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("邮箱"), {
    target: { value: "new@example.com" },
  });
  fireEvent.change(screen.getByLabelText("修改邮箱的当前密码"), {
    target: { value: "wrong" },
  });
  fireEvent.click(screen.getByRole("button", { name: "修改邮箱" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("邮箱")).toHaveValue("new@example.com");
  expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({
    email: "new@example.com",
    current_password: "wrong",
  });
});
it("successful password change returns to login", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ reauthenticate: true, email: "old@example.com" }),
          { status: 200 },
        ),
    ),
  );
  const changed = vi.fn();
  render(
    <ProfilePage
      email="old@example.com"
      onEmailSaved={() => {}}
      onPasswordChanged={changed}
      onDirty={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("修改密码的当前密码"), {
    target: { value: "123456" },
  });
  fireEvent.change(screen.getByLabelText("新密码"), {
    target: { value: "new-password-123" },
  });
  fireEvent.change(screen.getByLabelText("确认新密码"), {
    target: { value: "new-password-123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
  await screen.findByRole("status");
  expect(changed).toHaveBeenCalledOnce();
});
