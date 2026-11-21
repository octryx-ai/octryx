import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn } from "./helpers.mjs";

// The chat shell after the redesign: the chats list, the message box with its workflow, model and thinking controls,
// and the thread's trace. The old separate runtime, project and agent pickers are gone (the unified entry point), so
// none of them may come back.
test("chat shell renders compact workspace controls", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  await ensureSignedIn(page);
  await page.goto("/chat?new=true", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("textbox", { name: /Message Octryx/i })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Workflow", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: "Thinking", exact: true })).toBeVisible();
  await expect(page.locator(".workspace__header").getByRole("button", { name: /^Open execution trace/ })).toBeVisible();

  for (const removed of ["Runtime selection", "Project selection", "Mode selection",
    "Agent group selection", "Agent selection"]) {
    await expect(page.getByLabel(removed)).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: /manual routing/i })).toHaveCount(0);

  expect(runtimeErrors).toEqual([]);
});
