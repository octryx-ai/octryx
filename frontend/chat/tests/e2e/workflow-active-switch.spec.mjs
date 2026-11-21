import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea } from "./helpers.mjs";

// Agents › Workflows: a platform admin switches a workflow off and on again ('s POST /flows/{id}/active).
// Off only stops new starts. Nothing is mocked: the e2e server ships its workflows.
test("an admin switches a workflow off and on again in the Workflows list", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await openWorkspaceArea(page, "Agents & workflows");
  await page.goto("/chat?area=workflows&tab=workflowList", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("workflow-active-hint")).toContainText("runs already going keep running");

  const toggle = page.getByTestId("workflow-active-bug-fix-reproduction");
  await expect(toggle).toBeChecked();
  await toggle.click(); // the switch moves once the server saved it
  await expect(toggle).not.toBeChecked();
  await expect(toggle).toBeEnabled();

  // The list read again keeps the choice, and the workflow is still listed so it can be switched on.
  await page.reload({ waitUntil: "domcontentloaded" });
  const again = page.getByTestId("workflow-active-bug-fix-reproduction");
  await expect(again).not.toBeChecked();
  await again.click();
  await expect(again).toBeChecked();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("workflow-active-bug-fix-reproduction")).toBeChecked();
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});
