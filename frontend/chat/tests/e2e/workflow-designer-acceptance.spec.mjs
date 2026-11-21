import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn } from "./helpers.mjs";

// Workflow designer acceptance (Alex's test case): a new workflow from scratch,
//   Start → agent step "Triage" with possible results → condition "Fix needed?" → two branches
//   (Fix needed → agent step "Fix" → approval; Otherwise → approval) → approval → End,
// saved as a draft, the check messages read, fixed, saved clean, then publishing requested.
// Selectors: D2b1 canvas and the D2b side panel (node-inspector,
// edge-inspector). Unmocked: every message comes from the backend's validation.
//
// Run against a deployed instance (a login saved once by a person, never extracted):
//   OCTRYX_E2E_BASE_URL=https://<host> OCTRYX_E2E_STORAGE_STATE=<file> \
//     npx playwright test workflow-designer-acceptance --project=chromium --no-deps
// (--no-deps: the local admin login of the setup project does not apply to a remote instance; the saved session does.)
// Until the designer page exists the test skips with a reason instead of failing.

const NONCE = Date.now().toString(36);
const NAME = `Acceptance ${NONCE}`;
const DESIGNER_URL = "/chat?area=workflows&tab=workflowDesigner";

if (process.env.OCTRYX_E2E_STORAGE_STATE) test.use({ storageState: process.env.OCTRYX_E2E_STORAGE_STATE });
test.use({ viewport: { width: 1440, height: 900 } });
// An acceptance result must not be the second of two attempts.
test.describe.configure({ retries: 0 });

const nodes = (page) => page.getByTestId("designer-node");
const nodeById = (page, id) => page.locator(`[data-testid="designer-node"][data-node-id="${id}"]`);
const inspector = (page) => page.getByTestId("node-inspector");
// A side-panel select sits inside its label, so the label's text also holds the options and any problem line: match
// the label by its start, never exactly.
const choice = (scope, label) => scope.getByLabel(new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));

async function nodeIds(page) {
  return nodes(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-node-id")));
}

/** Adds a box by clicking its catalog entry (it lands on a free spot, selected) and returns its id. */
async function addBox(page, kind, name) {
  const before = new Set(await nodeIds(page));
  await page.locator(`[data-testid="designer-catalog-item"][data-kind="${kind}"]`).click();
  await expect.poll(async () => (await nodeIds(page)).length).toBe(before.size + 1);
  const id = (await nodeIds(page)).find((item) => !before.has(item));
  await select(page, id);
  if (name) await inspector(page).getByLabel("Name", { exact: true }).fill(name);
  return id;
}

/** The canvas pans and zooms by itself: bring every box into view before clicking one. */
async function fitView(page) {
  await page.getByRole("button", { name: "Fit View" }).click();
}

async function select(page, id) {
  await fitView(page);
  await nodeById(page, id).click();
  await expect(inspector(page)).toBeVisible();
}

/** Connects two boxes through the keyboard path (⋯ → Connect to… → target). */
async function connect(page, from, to) {
  await select(page, from);
  await nodeById(page, from).getByTestId("designer-node-menu").click();
  await page.getByTestId("designer-connect-to").click();
  await page.locator(`[data-testid="designer-connect-target"][data-node-id="${to}"]`).click();
  await expect(page.locator(`[data-testid="designer-edge"][data-source="${from}"][data-target="${to}"]`)).toHaveCount(1);
}

/** Sets for which result an arrow is taken, in the arrow's own panel. */
async function arrowWhen(page, from, to, label) {
  await fitView(page);
  // A short arrow's middle can lie under its target box: send the click to the arrow itself.
  await page.locator(`[data-testid="designer-edge"][data-source="${from}"][data-target="${to}"]`).dispatchEvent("click");
  const panel = page.getByTestId("edge-inspector");
  await expect(panel).toBeVisible();
  await choice(panel, "Taken when the result is").selectOption({ label });
}

async function fillAgentStep(page, id, { results } = {}) {
  await select(page, id);
  const panel = inspector(page);
  await choice(panel, "Agent").selectOption({ index: 1 });
  if (!(await panel.getByRole("button", { name: /Blocks|Only noted/ }).count())) {
    await panel.getByRole("button", { name: "Add a check" }).click();  // opens with the first kind of check chosen
  }
  for (const result of results ?? []) {
    await panel.getByLabel("The agent ends with one of: Add result").fill(result);
    await panel.getByRole("button", { name: "Add result" }).click();
  }
}

/** Saves and proves a new draft version was stored (2: a click on a busy button saved nothing). */
async function saveDraft(page) {
  const status = page.getByTestId("designer-status");
  const before = (await status.textContent().catch(() => "")) ?? "";
  const button = page.getByTestId("designer-save-draft");
  await expect(button).toBeEnabled();
  await button.click();
  await expect.poll(async () => (await status.textContent()) ?? "").not.toBe(before);
  await expect(status).toContainText(/draft/i);
  await expect(page.getByText("not saved yet")).toHaveCount(0);
}

test("Alex's case: from scratch to a clean draft and a publishing request", async ({ page }) => {
  const errors = collectRuntimeErrors(page);
  if (!process.env.OCTRYX_E2E_STORAGE_STATE) await ensureSignedIn(page);
  await page.goto(DESIGNER_URL);
  const designer = page.getByTestId("designer");
  // isVisible() does not wait: wait for the page to finish loading before deciding that the designer is absent.
  const present = await designer.waitFor({ state: "visible", timeout: 45_000 }).then(() => true, () => false);
  test.skip(!present, "The workflow designer (D2b1) is not deployed here yet.");

  // 1. A new, empty workflow with a name.
  await page.getByTestId("designer-new").click();
  await page.getByTestId("designer-name").fill(NAME);
  const startId = (await page.locator('[data-testid="designer-node"][data-kind="start"]').count())
    ? await page.locator('[data-testid="designer-node"][data-kind="start"]').first().getAttribute("data-node-id")
    : await addBox(page, "start");

  // 2. The boxes.
  const triage = await addBox(page, "phase", "Triage");
  const decision = await addBox(page, "decision", "Fix needed?");
  const fix = await addBox(page, "phase", "Fix");
  const approval = await addBox(page, "approval", "Approve the change");
  const done = await addBox(page, "outcome", "Done");
  const stopped = await addBox(page, "outcome", "Stopped");

  // 3. The straight arrows; the condition's branches come from its own panel.
  await connect(page, startId, triage);
  await connect(page, triage, decision);
  await connect(page, fix, approval);

  // 4. Save early: the draft is stored although it is incomplete, and the checks say what is missing.
  await saveDraft(page);
  const issues = page.getByTestId("designer-issue");
  await expect(issues.first()).toBeVisible();
  const firstCount = await issues.count();
  expect(firstCount).toBeGreaterThan(0);
  // A problem leads to its box.
  const target = await issues.first().getAttribute("data-node-id");
  if (target) {
    await issues.first().click();
    await expect(inspector(page)).toBeVisible();
  }

  // 5. Fix everything the checks named.
  await fillAgentStep(page, triage, { results: ["Fix needed", "No fix"] });
  await fillAgentStep(page, fix);

  await select(page, decision);
  const panel = inspector(page);
  const looksAt = panel.getByLabel(/^Looks at(?! the result)/);
  if (await looksAt.count()) await looksAt.selectOption({ label: "The result of a step" });
  await panel.getByLabel(/^(Step|Looks at the result of)/).selectOption({ label: "Triage (Agent step)" });
  await panel.getByLabel("Where the run goes: Fix needed").selectOption({ label: "Fix" });
  await panel.getByLabel("Where the run goes: Otherwise").selectOption({ label: "Approve the change" });
  await expect(page.locator(`[data-testid="designer-edge"][data-source="${decision}"][data-when="fix_needed"]`)).toHaveCount(1);
  await expect(page.locator(`[data-testid="designer-edge"][data-source="${decision}"][data-when="otherwise"]`)).toHaveCount(1);

  await select(page, approval);
  await inspector(page).getByLabel("What is approved").fill("Merge the change");
  await connect(page, approval, done);
  await arrowWhen(page, approval, done, "Approved");
  await connect(page, approval, stopped);
  await arrowWhen(page, approval, stopped, "Rejected");
  await select(page, stopped);
  await choice(inspector(page), "The workflow ends as").selectOption({ label: "Stopped" });

  // 6. Saved again: no problem left.
  await saveDraft(page);
  await expect(issues).toHaveCount(0);

  // 7. Ask for publishing (four eyes): open for a valid, saved draft.
  const request = page.getByTestId("designer-request-publish");
  await expect(request).toBeEnabled();
  await request.click();
  await expect(page.getByTestId("designer-status")).toContainText(/review/i);

  expect(errors).toEqual([]);
});
