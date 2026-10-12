import { test, expect } from "@playwright/test";

test("storage management navigation and filesystem creation reuse saved connection", async ({
  page,
}) => {
  const errors: string[] = [];
  const submitted: any[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const storage = {
    id: "s1",
    name: "共享 S3",
    storage_type: "s3",
    description: "团队测试",
    enabled: true,
    revision: 2,
    can_manage: true,
    has_secrets: true,
    creator_id: "u1",
    created_at: "2026-10-08T00:00:00Z",
    updated_at: "2026-10-08T00:00:00Z",
    parameters: {
      s3_endpoint: "http://s3.example:9000",
      s3_bucketname: "test-bucket",
    },
  };
  const operation = {
    id: "create1",
    action: "fs.create",
    state: "succeeded",
    result: { steps: [] },
  };
  const snapshot = {
    machines: [],
    resources: [],
    operations: [],
    storage_profiles: [storage],
    catalog: [
      {
        action: "fs.create",
        label: "创建文件系统",
        section: "filesystem",
        mutating: true,
        fields: [
          {
            key: "fs_name",
            label: "文件系统名称",
            type: "text",
            required: true,
          },
          {
            key: "partition_type",
            label: "分区类型",
            type: "select",
            options: ["hash", "monolithic"],
            default: "hash",
          },
          { key: "storage_profile_id", label: "存储配置", type: "text" },
          { key: "storage_profile_revision", label: "版本", type: "number" },
        ],
      },
    ],
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
          csrf_token: "csrf",
        },
      });
    if (path.endsWith("/clusters/c1"))
      return route.fulfill({
        json: {
          id: "c1",
          external_name: "test-cluster",
          name: "测试",
          creator_id: "u1",
          revision: 1,
          archived: false,
          binding_state: "verified",
        },
      });
    if (path.endsWith("/resources")) return route.fulfill({ json: snapshot });
    if (path.endsWith("/storage-profiles"))
      return route.fulfill({ json: [storage] });
    if (path.endsWith("/resource-operations") && request.method() === "POST") {
      submitted.push(request.postDataJSON());
      return route.fulfill({ json: operation });
    }
    return route.fulfill({
      status: 500,
      json: { detail: "unexpected mock endpoint" },
    });
  });
  await page.goto("/#/clusters/c1/resources");
  await page
    .getByLabel("文件系统名称", { exact: true })
    .fill("browser-test-fs");
  await page.getByRole("combobox", { name: "存储配置", exact: true }).selectOption("s1");
  await expect(page.getByText("test-bucket", { exact: true })).toBeVisible();
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("共享 S3");
    await dialog.accept();
  });
  await page
    .getByRole("button", { name: "执行创建文件系统", exact: true })
    .click();
  await expect.poll(() => submitted.length).toBe(1);
  expect(submitted[0].parameters).toEqual({
    fs_name: "browser-test-fs",
    partition_type: "hash",
    storage_profile_id: "s1",
    storage_profile_revision: 2,
  });
  await page.getByRole("link", { name: "管理存储配置" }).click();
  await expect(page).toHaveURL(/#\/storage$/);
  await expect(
    page.getByRole("heading", { name: "存储配置", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("共享 S3", { exact: true })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("storage-profiles.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
