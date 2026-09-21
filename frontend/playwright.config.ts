import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: process.env.PLATFORM_E2E_URL || "http://127.0.0.1:55173",
    headless: true,
    trace: "retain-on-failure",
  },
  reporter: "list",
});
