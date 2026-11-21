import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn, openWorkspaceArea } from "./helpers.mjs";

// Chat, Admin and the account menu stay interactive one after the other.
test("chat workspace, admin area, and profile menu remain interactive", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  await ensureSignedIn(page);
  await expect(page.getByRole("textbox", { name: /Message Octryx/i })).toBeVisible();

  await openWorkspaceArea(page, "Admin");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();

  await openWorkspaceArea(page, "Chat");
  await expect(page.getByRole("textbox", { name: /Message Octryx/i })).toBeVisible();

  await page.getByRole("button", { name: "Account" }).click();
  await expect(page.getByRole("button", { name: "Log out" }).or(page.getByRole("menuitem", { name: "Log out" }))).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});
