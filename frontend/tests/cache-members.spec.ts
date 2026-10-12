import { test, expect } from "@playwright/test";

test("queried external cache members can be selected and deletion requires confirmation", async ({
  page,
}) => {
  const errors: string[] = [];
  const submitted: any[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let members = [
    ...Array.from({ length: 62 }, (_, i) => ({
      member_id: `external-${i}`,
      group_name: `cache-group-${i % 4}`,
      ip: "192.0.2.1",
      port: 21000 + i,
      state: 3,
    })),
    {
      member_id: "online-member",
      group_name: "live-cache",
      ip: "192.0.2.2",
      port: 9300,
      state: 1,
    },
  ];
  const listing = (id: string) => ({
    id,
    action: "cache.list",
    state: "succeeded",
    created_at: new Date().toISOString(),
    result: {
      steps: [
        {
          data: {
            groups: { result: { groups: [] } },
            members: { result: { members: [...members] } },
          },
        },
      ],
    },
  });
  const snapshot = {
    catalog: [
      {
        action: "cache.list",
        label: "缓存组与成员列表",
        section: "cache",
        mutating: false,
        fields: [],
      },
      {
        action: "cache.delete",
        label: "删除缓存组成员登记",
        section: "cache",
        mutating: true,
        fields: [
          {
            key: "member_id",
            label: "缓存组成员",
            type: "text",
            required: true,
          },
        ],
      },
    ],
    machines: [],
    resources: [],
    operations: [listing("initial-query")],
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u1",
          username: "admin",
          email: "admin@example.test",
          role: "admin",
          csrf_token: "test",
        },
      });
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          external_name: "main-dingofs",
          name: "测试",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources")) return route.fulfill({ json: snapshot });
    if (path.endsWith("/resource-operations") && request.method() === "POST") {
      const body = request.postDataJSON();
      submitted.push(body);
      let operation: any;
      if (body.action === "cache.delete") {
        members = members.filter(
          (member) => member.member_id !== body.parameters.member_id,
        );
        operation = {
          id: "deleted",
          action: "cache.delete",
          state: "succeeded",
          payload: body.parameters,
          created_at: new Date().toISOString(),
          result: {
            steps: [
              {
                data: { member_id: body.parameters.member_id },
                remote_state: "deleted",
                returncode: 0,
              },
            ],
          },
        };
      } else if (body.action === "cache.list")
        operation = listing("refreshed-query");
      else throw new Error("unexpected action " + body.action);
      snapshot.operations.unshift(operation);
      return route.fulfill({ json: operation });
    }
    return route.fulfill({
      status: 500,
      json: { detail: "unexpected API " + path },
    });
  });
  await page.goto("/#/clusters/c1/resources");
  await page
    .getByRole("navigation", { name: "资源功能", exact: true })
    .getByRole("button", { name: /缓存组/ })
    .click();
  await page
    .getByRole("button", { name: "删除缓存组成员登记", exact: true })
    .click();
  const select = page.getByRole("combobox", {
    name: "缓存组成员",
    exact: true,
  });
  await expect(select.locator("option")).toHaveCount(64);
  await expect(select.locator('option[value="external-17"]')).toContainText(
    "cache-group-1",
  );
  await expect(select.locator('option[value="external-17"]')).toContainText(
    "192.0.2.1:21017",
  );
  await expect(select.locator('option[value="online-member"]')).toHaveJSProperty("disabled", true);
  expect(submitted).toEqual([]);
  await select.selectOption("external-17");
  await page.screenshot({
    path: test.info().outputPath("cache-member-selection.png"),
    fullPage: true,
  });
  const execute = page.getByRole("button", {
    name: "执行删除缓存组成员登记",
    exact: true,
  });
  page.once("dialog", (dialog) => dialog.dismiss());
  await execute.click();
  expect(submitted).toEqual([]);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("external-17");
    await dialog.accept();
  });
  await execute.click();
  await expect.poll(() => submitted.length).toBe(1);
  expect(submitted[0]).toMatchObject({
    action: "cache.delete",
    parameters: { member_id: "external-17" },
    confirmed: true,
  });
  await page
    .getByRole("button", { name: "刷新缓存成员列表", exact: true })
    .click();
  await expect.poll(() => submitted.length).toBe(2);
  await expect(select.locator('option[value="external-17"]')).toHaveCount(0);
  await expect(execute).toBeDisabled();
  expect(errors).toEqual([]);
});
