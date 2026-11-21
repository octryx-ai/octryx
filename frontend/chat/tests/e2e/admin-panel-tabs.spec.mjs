import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea } from "./helpers.mjs";

// Every area of the rail opens as the current page, with its page heading, and without a console or page error.
test("workspace areas open without runtime errors", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const rail = page.getByRole("navigation", { name: "Workspace areas" });

  for (const area of ["Chat", "Knowledge", "Work", "Agents", "Operations", "Admin"]) {
    await openWorkspaceArea(page, area);
    await expect(rail.getByRole("button", { name: area, exact: true })).toHaveAttribute("aria-current", "page");
    if (area === "Chat") await expect(page.getByRole("textbox", { name: /Message Octryx/i })).toBeVisible();
    else await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    expect(runtimeErrors, `runtime errors after opening ${area}`).toEqual([]);
  }
});
