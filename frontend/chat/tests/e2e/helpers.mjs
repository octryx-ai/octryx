import { expect } from "@playwright/test";

export const username = process.env.OCTRYX_E2E_USERNAME ?? "admin";
export const password = process.env.OCTRYX_E2E_PASSWORD ?? "admin";

export async function waitOutRateLimit(page) {
  const bodyText = await page.locator("body").textContent({ timeout: 1000 }).catch(() => "");
  const match = /Rate limit exceeded\. Retry after (\d+) seconds?/i.exec(bodyText ?? "");
  if (!match) {
    return false;
  }
  await page.waitForTimeout((Number(match[1]) + 1) * 1000);
  return true;
}

async function submitLogin(page) {
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function ensureSignedIn(page) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.goto("/chat", { waitUntil: "domcontentloaded" });

    const loginInput = page.locator('input[name="username"]');
    const loginVisible = await loginInput.isVisible({ timeout: 3000 }).catch(() => false);
    if (loginVisible) {
      await submitLogin(page);
    }

    if (await waitOutRateLimit(page)) {
      continue;
    }

    if (await isWorkspaceShellVisible(page)) {
      return;
    }
  }

  await expectWorkspaceShellVisible(page);
}

async function isWorkspaceShellVisible(page) {
  const chatWorkspaceVisible = await page
    .getByText("Chats", { exact: true })
    .isVisible({ timeout: 5000 })
    .catch(() => false);
  if (chatWorkspaceVisible) {
    return true;
  }
  return page
    .getByRole("button", { name: "Work", exact: true })
    .isVisible({ timeout: 5000 })
    .catch(() => false);
}

export async function expectWorkspaceShellVisible(page) {
  await expect(
    page
      .getByText("Chats", { exact: true })
      .or(page.getByRole("button", { name: "Work", exact: true }))
      .first(),
  ).toBeVisible({ timeout: 15_000 });
}

// Areas without their own rail entry open by URL.
const AREA_ADDRESSES = {
  Coding: "area=coding",
  Automation: "area=admin&tab=connectors",
  Runtime: "area=admin&tab=providers",
  Settings: "area=admin&tab=users",
  "Agents & workflows": "area=workflows",
};

export async function openWorkspaceArea(page, name) {
  await ensureSignedIn(page);
  if (AREA_ADDRESSES[name]) {
    await page.goto(`/chat?${AREA_ADDRESSES[name]}`, { waitUntil: "domcontentloaded" });
    if (await waitOutRateLimit(page)) await page.reload({ waitUntil: "domcontentloaded" });
    return;
  }
  const areaButton = page.getByRole("navigation", { name: "Workspace areas" }).getByRole("button", { name, exact: true });
  await expect(areaButton).toBeVisible();
  await areaButton.click();
  if (await waitOutRateLimit(page)) {
    await page.reload({ waitUntil: "domcontentloaded" });
  }
}

export function collectRuntimeErrors(page) {
  const runtimeErrors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") {
      return;
    }
    const text = message.text();
    if (text.includes("favicon.ico")) {
      return;
    }
    runtimeErrors.push(`console: ${text}`);
  });
  page.on("pageerror", (error) => {
    runtimeErrors.push(`pageerror: ${error.message}`);
  });
  return runtimeErrors;
}

// A fresh e2e database has no chats; specs that need some start them through the chat's own send route.
export async function seedChats(page, count) {
  await ensureSignedIn(page);
  for (let index = 0; index < count; index += 1) {
    const answer = await page.evaluate(async (prompt) => {
      const response = await fetch("/chat/api/send", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }) });
      return { status: response.status, text: (await response.text()).slice(0, 300) };
    }, `e2e seed chat ${index + 1}`);
    expect(answer.status, answer.text).toBeLessThan(300);
  }
  await page.reload({ waitUntil: "domcontentloaded" });
}
