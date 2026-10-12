import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const catalog = JSON.parse(
  readFileSync(
    new URL("./fixtures/resource-catalog.json", import.meta.url),
    "utf8",
  ),
);
for (const external of [false, true])
  test(`group and member actions confirm fixed targets and refresh the inventory (external=${external})`, async ({
    page,
  }) => {
    const members = ["a", "b"].map((id, i) => ({
      member_id: id,
      group_name: "g",
      ip: "192.0.2.1",
      port: 21000 + i,
      state: 1,
    }));
    const submitted: any[] = [];
    const operations: any[] = [];
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let serial = 0;
    const listing = () => ({
      id: `list-${++serial}`,
      action: "cache.list",
      state: "succeeded",
      created_at: new Date(Date.now() + serial * 1000).toISOString(),
      result: {
        steps: [
          {
            data: {
              groups: { result: { group_names: members.length ? ["g"] : [] } },
              members: { result: { members: members.map((m) => ({ ...m })) } },
            },
          },
        ],
      },
    });
    operations.push(listing());
    const resources = ["a", "b"].map((id) => ({
      id: `r-${id}`,
      name: "g",
      kind: "cache",
      state: "running",
      created_at: "2026-10-10",
      data: {
        members: [{ member_id: id, machine_id: "m", target_user: "root" }],
      },
    }));
    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      if (path.endsWith("/auth/me"))
        return route.fulfill({
          json: {
            id: "u",
            username: "admin",
            email: "a@example.test",
            role: "admin",
            csrf_token: "test",
          },
        });
      if (path.endsWith("/clusters/c1"))
        return route.fulfill({
          json: {
            id: "c1",
            external_name: "cluster",
            name: "cluster",
            revision: 1,
            creator_id: "u",
            binding_state: "verified",
            archived: false,
          },
        });
      if (path.endsWith("/resources"))
        return route.fulfill({
          json: {
            catalog: catalog.filter((a: any) => a.section === "cache"),
            resources: external ? [] : resources,
            cache_member_targets: external
              ? Object.fromEntries(
                  members.map((m) => [
                    m.member_id,
                    { machine_id: "m", target_user: "root", can_stop: true },
                  ]),
                )
              : {},
            machines: [],
            operations,
          },
        });
      if (path.endsWith("/resource-operations") && req.method() === "POST") {
        const body = req.postDataJSON();
        submitted.push(body);
        let op: any;
        if (body.action === "cache.list") op = listing();
        else {
          const ids = body.parameters.member_ids || [body.parameters.member_id];
          if (body.action === "cache.stop")
            members.forEach((m) => {
              if (ids.includes(m.member_id)) {
                m.state = 3;
                resources.find((r) => r.id === `r-${m.member_id}`)!.state =
                  "stopped";
              }
            });
          else
            for (let i = members.length - 1; i >= 0; i--)
              if (ids.includes(members[i].member_id)) members.splice(i, 1);
          op = {
            id: `op-${++serial}`,
            action: body.action,
            payload: body.parameters,
            state: "succeeded",
            created_at: new Date(Date.now() + serial * 1000).toISOString(),
            result: {
              steps: ids.map((member_id: string) => ({
                member_id,
                failed: false,
                returncode: 0,
              })),
            },
          };
        }
        operations.unshift(op);
        return route.fulfill({ json: op });
      }
      return route.fulfill({
        status: 500,
        json: { message: `unexpected ${path}` },
      });
    });
    await page.goto("/#/clusters/c1/resources");
    await page
      .getByRole("navigation", { name: "资源功能" })
      .getByRole("button", { name: /缓存组/ })
      .click();
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "停止 g", exact: true }).click();
    expect(submitted).toHaveLength(0);
    await page.getByText("成员信息", { exact: true }).click();
    const table = page.getByRole("table", { name: "g 成员列表", exact: true });
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("b");
      await dialog.accept();
    });
    await table
      .getByRole("button", { name: "停止成员 b", exact: true })
      .click();
    await expect(
      table
        .getByRole("row")
        .filter({
          has: page.getByRole("button", { name: "删除成员 b", exact: true }),
        }),
    ).toContainText("离线");
    await expect(
      table.getByRole("button", { name: "停止成员 a", exact: true }),
    ).toBeEnabled();
    expect(submitted.find((x) => x.action === "cache.stop").parameters).toEqual(
      {
        member_ids: ["b"],
      },
    );
    page.once("dialog", (dialog) => dialog.accept());
    await table
      .getByRole("button", { name: "删除成员 b", exact: true })
      .click();
    await expect(
      table.getByRole("button", { name: "删除成员 b", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "停止 g", exact: true }),
    ).toBeEnabled();
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "停止 g", exact: true }).click();
    await expect(
      table
        .getByRole("row")
        .filter({
          has: page.getByRole("button", { name: "删除成员 a", exact: true }),
        }),
    ).toContainText("离线");
    await expect(
      page.getByRole("button", { name: "删除 g", exact: true }),
    ).toBeEnabled();
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "删除 g", exact: true }).click();
    await expect(
      page.getByRole("rowheader", { name: "g", exact: true }),
    ).toHaveCount(0);
    expect(
      submitted
        .filter((x) => x.action === "cache.stop")
        .map((x) => x.parameters),
    ).toEqual([{ member_ids: ["b"] }, { member_ids: ["a"] }]);
    expect(errors).toEqual([]);
  });
