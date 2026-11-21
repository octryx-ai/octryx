import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea } from "./helpers.mjs";

// An instance without knowledge storage (the e2e server has none) says so with the administrator's next step,
// not with a red "not configured" box (outsider walkthrough). Nothing is mocked.
test("a search on an instance without knowledge storage names the state and the next step", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await openWorkspaceArea(page, "Knowledge");
  const field = page.getByPlaceholder(/Ask a question/);
  await field.fill("rollback");
  await field.press("Enter");

  const refusal = page.getByTestId("search-refusal");
  await expect(refusal).toContainText("Knowledge storage is not set up on this instance");
  await expect(refusal).toContainText("deployment's configuration");
  await expect(refusal.getByRole("link", { name: "How to set up knowledge storage" }))
    .toHaveAttribute("href", "https://octryx.ai/docs/install/knowledge-storage#object-store");
  await expect(page.locator(".knowledge-search__error")).toHaveCount(0);
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});
