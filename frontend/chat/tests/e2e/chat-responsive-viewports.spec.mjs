import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn } from "./helpers.mjs";

// Narrow-viewport chat workspace. The four viewports are the ones the
// issue reproduces; the assertions are the acceptance contract, not a visual
// snapshot: nothing overlaps, the conversation keeps the vertical budget, and
// the thread's trace is reachable without a menu.

const VIEWPORTS = [
  { label: "390x844", width: 390, height: 844, phone: true },
  { label: "430x932", width: 430, height: 932, phone: true },
  { label: "768x1024", width: 768, height: 1024, phone: false },
  { label: "1440x1000", width: 1440, height: 1000, phone: false },
];

async function boxOf(locator) {
  const box = await locator.boundingBox();
  expect(box, "element has no layout box").not.toBeNull();
  return box;
}

for (const viewport of VIEWPORTS) {
  test(`chat workspace stays usable at ${viewport.label}`, async ({ page }) => {
    const runtimeErrors = collectRuntimeErrors(page);
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await ensureSignedIn(page);

    const header = page.locator(".workspace__header");
    const feed = page
      .locator(".workspace__feed-shell, .workspace__feed")
      .first();
    const composer = page.locator(".composer-shell");

    const headerBox = await boxOf(header);
    const feedBox = await boxOf(feed);
    const composerBox = await boxOf(composer);

    // Header, conversation and composer are stacked, never overlapping.
    expect(headerBox.y + headerBox.height).toBeLessThanOrEqual(feedBox.y + 1);
    expect(feedBox.y + feedBox.height).toBeLessThanOrEqual(composerBox.y + 1);
    expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(
      viewport.height + 1,
    );

    // The conversation keeps the larger share of the viewport.
    expect(feedBox.height).toBeGreaterThan(composerBox.height);
    if (viewport.phone) {
      expect(composerBox.height).toBeLessThan(viewport.height * 0.34);
    }

    // Primary message entry and send/stop stay visible at every width.
    await expect(
      page.getByRole("textbox", { name: /Message Octryx/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^(Send message|Stop run)$/ }),
    ).toBeVisible();

    // The thread's trace stays one click away in the header at every width.
    await expect(page.locator(".workspace__header").getByRole("button", { name: /^Open execution trace/ })).toBeVisible();

    expect(runtimeErrors).toEqual([]);
  });
}
