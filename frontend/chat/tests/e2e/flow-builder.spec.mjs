import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea, waitOutRateLimit } from "./helpers.mjs";

const SHIPPED = "Bug fix with a reproduction test";

// Agents › Workflows: the list of the workflows agents run (the shipped ones included).
async function openWorkflowLibrary(page) {
  await openWorkspaceArea(page, "Agents");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  if (await waitOutRateLimit(page)) {
    await page.reload({ waitUntil: "domcontentloaded" });
  }
  await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Search workflows" })).toBeVisible();
}

test("the Workflows page lists the shipped workflow definitions without errors", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  await openWorkflowLibrary(page);

  await expect(page.getByRole("row").filter({ hasText: SHIPPED })).toBeVisible();
  await expect(page.getByRole("button", { name: "New workflow" })).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});

test("a workflow opens in the editor with its canvas without errors", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  await openWorkflowLibrary(page);
  await page.getByRole("row").filter({ hasText: SHIPPED }).click();

  await expect(page.locator(".react-flow")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".react-flow__node").first()).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});
