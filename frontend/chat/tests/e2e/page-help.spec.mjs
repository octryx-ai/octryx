import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn, openWorkspaceArea } from "./helpers.mjs";

// The rail's help opens the help of the area on screen: each area has its own title, the drawer names it, and
// "Close help" closes it.
test("global page help follows the active workspace area", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const titles = [];

  for (const area of ["Chat", "Knowledge", "Work", "Agents", "Operations", "Admin"]) {
    await openWorkspaceArea(page, area);
    // The area may open a sub-page after it appeared (Admin opens People & sign-in): help opens once the page is quiet.
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Open page help" }).click();
    const drawer = page.getByTestId("page-help");
    await expect(drawer).toBeVisible();
    // The drawer's heading and its accessible name agree, and stay so (a title read in a page switch would change).
    const read = async () => {
      const heading = (await drawer.getByRole("heading", { level: 2 }).first().textContent())?.trim() ?? "";
      return heading && (await drawer.getAttribute("aria-label")) === `${heading} help` ? heading : "";
    };
    let title = "";
    await expect.poll(async () => {
      const first = await read();
      await page.waitForTimeout(300);
      title = first && first === (await read()) ? first : "";
      return title;
    }, { message: `help title in ${area}`, timeout: 15_000 }).not.toBe("");
    await expect(drawer).toHaveAccessibleName(`${title} help`);
    titles.push(title);
    await drawer.getByRole("button", { name: "Close help" }).click();
    await expect(drawer).toBeHidden();
  }

  expect(titles[0]).toBe("Chat");
  expect(new Set(titles).size, `help titles: ${titles.join(", ")}`).toBe(titles.length);
  expect(runtimeErrors).toEqual([]);
});

// On a phone the help is a sheet over the page: the page must not show through it (outsider walkthrough).
test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the help sheet covers the page", async ({ page }) => {
    await ensureSignedIn(page);
    await page.goto("/chat?area=knowledge", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Help for this page" }).first().click();
    const sheet = page.getByTestId("page-help").locator(".page-help__drawer");
    await expect(sheet).toBeVisible();
    const color = await sheet.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(color, "the sheet's base colour").not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  });
});
