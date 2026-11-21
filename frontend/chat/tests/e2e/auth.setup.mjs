import { test } from "@playwright/test";

import { expectWorkspaceShellVisible, password, username, waitOutRateLimit } from "./helpers.mjs";

const authFile = "tests/e2e/.auth/admin.json";

test("authenticate admin user", async ({ page }) => {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.goto("/chat", { waitUntil: "domcontentloaded" });

    const usernameInput = page.locator('input[name="username"]');
    if (await usernameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await usernameInput.fill(username);
      await page.locator('input[name="password"]').fill(password);
      await page.getByRole("button", { name: "Sign in" }).click();
    }

    if (await waitOutRateLimit(page)) {
      continue;
    }

    const shellReady =
      (await page.getByText("Chats", { exact: true }).isVisible({ timeout: 5000 }).catch(() => false)) ||
      (await page.getByRole("button", { name: "Work", exact: true }).isVisible({ timeout: 5000 }).catch(() => false));
    if (shellReady) {
      await page.context().storageState({ path: authFile });
      return;
    }
  }

  await expectWorkspaceShellVisible(page);
  await page.context().storageState({ path: authFile });
});
