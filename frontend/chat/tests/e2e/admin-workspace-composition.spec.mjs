import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea } from "./helpers.mjs";

// Admin › Workspaces lists the Workspaces and offers to create one.
test("admin workspaces page exposes workspace administration without runtime errors", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  await openWorkspaceArea(page, "Admin");
  await page.getByRole("button", { name: "Workspaces", exact: true }).first().click();

  await expect(page.getByRole("heading", { level: 1, name: /Workspaces/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create workspace" })).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});
