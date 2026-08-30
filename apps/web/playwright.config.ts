import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../../artifacts/playwright",
  // The guided acceptance flow intentionally mutates the shared seeded demo.
  // A single worker keeps screenshots and replay assertions reproducible.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: [
    [
      "html",
      { outputFolder: "../../artifacts/playwright-report", open: "never" },
    ],
  ],
  use: {
    baseURL: process.env.EHRFS_E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: process.env.EHRFS_E2E_EXTERNAL
    ? undefined
    : {
        command: "pnpm dev",
        url: "http://localhost:3000",
        reuseExistingServer: !process.env.CI,
      },
});
