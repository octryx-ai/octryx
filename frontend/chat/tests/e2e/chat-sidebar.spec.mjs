import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn, seedChats } from "./helpers.mjs";

// Chat sidebar acceptance: at 1280 and 390 px,
// in light and dark, the sidebar has no horizontal overflow and no serious axe violation; a keyboard-only
// walk selects chats, archives them through the confirm dialog and undoes it. The suite starts three chats
// first (a fresh database has none). axe runs when OCTRYX_E2E_AXE_PATH points at axe.min.js.

const VIEWPORTS = [
  { label: "1280", width: 1280, height: 860 },
  { label: "390", width: 390, height: 844 },
];
const THEMES = ["light", "dark"];
const AXE_PATH = process.env.OCTRYX_E2E_AXE_PATH ?? "";
// Optional evidence screenshots (normal and bulk mode) into this directory.
const SHOTS_DIR = process.env.OCTRYX_E2E_SHOTS_DIR ?? "";

async function openChat(page, { width, height }, theme) {
  await page.setViewportSize({ width, height });
  await page.addInitScript((value) => window.localStorage.setItem("octryx-chat-theme", value), theme);
  await ensureSignedIn(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  // Phone: the chat list is a drawer behind the header's "Open chats" button.
  const openChats = page.getByRole("button", { name: "Open chats" });
  if (width <= 760 && (await openChats.isVisible())) {
    await openChats.click();
    await expect(page.getByRole("button", { name: "Select chats" })).toBeInViewport({ ratio: 1 });
  }
  await expect(page.getByRole("searchbox", { name: "Search all chats" })).toBeVisible();
}

async function seriousAxeViolations(page) {
  await page.addScriptTag({ content: readFileSync(AXE_PATH, "utf8") });
  return page.evaluate(async () => {
    const result = await window.axe.run(".sidebar", { resultTypes: ["violations"] });
    return result.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map(
        (violation) =>
          `${violation.id}: ${violation.nodes.map((node) => `${node.target.join(" ")} — ${node.failureSummary}`).join("; ")}`,
      );
  });
}

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await seedChats(page, 3);
  await page.close();
});

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test(`chat sidebar at ${viewport.label}px, ${theme}: no overflow, no serious axe violation`, async ({ page }) => {
      const runtimeErrors = collectRuntimeErrors(page);
      await openChat(page, viewport, theme);

      const overflow = await page.evaluate(() => {
        const sidebar = document.querySelector(".sidebar__threads");
        return {
          page: document.scrollingElement.scrollWidth - window.innerWidth,
          list: sidebar ? sidebar.scrollWidth - sidebar.clientWidth : 0,
        };
      });
      expect(overflow.page).toBeLessThanOrEqual(0);
      expect(overflow.list).toBeLessThanOrEqual(0);

      if (SHOTS_DIR) {
        await page.screenshot({ path: `${SHOTS_DIR}/sidebar-${viewport.label}-${theme}.png` });
      }
      await page.getByRole("button", { name: "Select chats" }).click();
      await page.locator(".thread-group__check input").first().check();
      await expect(page.locator(".sidebar__bulk-count")).toContainText("selected");
      if (SHOTS_DIR) {
        await page.screenshot({ path: `${SHOTS_DIR}/sidebar-${viewport.label}-${theme}-bulk.png` });
      }
      if (AXE_PATH) {
        expect(await seriousAxeViolations(page)).toEqual([]);
      }
      await page.keyboard.press("Escape");
      await expect(page.locator(".sidebar__bulk-bar")).toHaveCount(0);
      expect(runtimeErrors).toEqual([]);
    });
  }
}

test("keyboard only: select chats, archive them after confirming, undo", async ({ page }) => {
  await openChat(page, VIEWPORTS[0], "dark");
  const focusedClass = () => page.evaluate(() => document.activeElement?.className ?? "");

  // "/" focuses the search; Tab moves on until a chat row has the focus.
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox", { name: "Search all chats" })).toBeFocused();
  for (let step = 0; step < 12 && !/\bthread-card\b/.test(await focusedClass()); step += 1) {
    await page.keyboard.press("Tab");
  }
  expect(await focusedClass()).toMatch(/\bthread-card\b/);

  // X starts the selection with this row, ↓ moves, Space toggles the next row too.
  await page.keyboard.press("x");
  await expect(page.locator(".sidebar__bulk-count")).toContainText("1 chat selected");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Space");
  await expect(page.locator(".sidebar__bulk-count")).toContainText("2 chats selected");

  for (let step = 0; step < 80 && !(await focusedClass()).includes("admin-panel__action-btn"); step += 1) {
    await page.keyboard.press("Tab");
  }
  await expect(page.getByRole("button", { name: "Archive 2" })).toBeFocused();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Archive 2 chats?");
  const confirm = dialog.getByRole("button", { name: "Archive 2 chats" });
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Enter");

  const toast = page.locator(".thread-bulk-toast");
  await expect(toast).toContainText("2 chats archived.");
  await expect(toast.getByRole("button", { name: "Undo" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(toast).toContainText("2 chats restored.");
});
