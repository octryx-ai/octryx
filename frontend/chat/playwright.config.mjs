import { defineConfig, devices } from "@playwright/test";

const isCi = Boolean(process.env.CI);
// Defaults to the local admin server. A worktree without its own backend venv
// can point the harness at an already running instance on another port.
const baseURL = process.env.OCTRYX_E2E_BASE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  timeout: 120_000,
  expect: {
    // On a busy machine the first page load can take longer than 5 s (the chat bootstrap request is still in
    // flight). A longer wait, not a weaker check.
    timeout: 15_000,
  },
  reporter: "list",
  retries: 1,
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.mjs/,
    },
    {
      name: "chromium",
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "./tests/e2e/.auth/admin.json",
      },
    },
  ],
  webServer: {
    command: "./scripts/run-admin-e2e-server.sh",
    url: `${baseURL}/admin/login`,
    reuseExistingServer: !isCi,
    timeout: 120_000,
  },
});
