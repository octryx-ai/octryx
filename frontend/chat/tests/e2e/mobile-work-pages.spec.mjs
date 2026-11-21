import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn } from "./helpers.mjs";

// On a phone the Work area's own menu is hidden; its pages are in the compact menu at the top (outsider walkthrough
// Work opened Runs and Work items could not be reached).
test.use({ viewport: { width: 390, height: 844 } });

async function openFromMenu(page, name) {
  await page.getByRole("button", { name: /^Navigation menu:/ }).or(page.locator("summary[aria-label^='Navigation menu']")).first().click();
  await page.getByRole("navigation", { name: "Workspace navigation" }).getByRole("button", { name, exact: true }).click();
}

test("a phone reaches every Work page from the compact menu", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await ensureSignedIn(page);

  await openFromMenu(page, "Work items");
  await expect(page.getByRole("heading", { level: 1, name: "Work items" })).toBeVisible();
  await expect(page).toHaveURL(/work_view=board/);

  // A second Work page while Work is open switches the page.
  await openFromMenu(page, "Plans");
  await expect(page).toHaveURL(/work_view=plans/);

  // A Coding-hosted page of the same menu.
  await openFromMenu(page, "Coding sessions");
  await expect(page).toHaveURL(/coding_view=sessions/);
  await expect(page.getByRole("heading", { level: 1, name: "Coding sessions" })).toBeVisible();

  await openFromMenu(page, "Work items");
  await expect(page.getByRole("heading", { level: 1, name: "Work items" })).toBeVisible();
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});
