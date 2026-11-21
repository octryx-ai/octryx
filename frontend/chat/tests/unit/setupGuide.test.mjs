// Setup guide (UX decision B): seven steps in a fixed order, done / open / attention from the server,
// the recommended ones (SSO, Roles) can be skipped without counting as open, "Setup: n of 7 done" only while a
// required step is open, and every step has its help file with one link into the page where it is done.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { helpLinkTarget, parseHelpDoc } from "../../src/help/helpDocs.ts";
import { resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";
import {
  SETUP_STEP_KEYS, applySkips, readSetupStatus, readSkips, setupProgressText, setupSummary, stepHref, unknownSteps, writeSkips,
} from "../../src/chat/setup/setupGuideModel.ts";

const payload = (statuses) => ({
  workspace: { id: "ws-1", name: "ux-first-run" },
  steps: Object.entries(statuses).map(([key, status]) => ({ key, status, reason: status === "attention" ? `${key} reason` : "" })),
});

test("the steps keep their order, scope and kind whatever the server sends", () => {
  const read = readSetupStatus(payload({ agents: "done", workspace: "done", bogus: "done", models: "attention" }));
  assert.deepEqual(read.steps.map((step) => step.key), [...SETUP_STEP_KEYS]);
  assert.deepEqual(read.steps.map((step) => step.scope),
    ["platform", "workspace", "workspace", "platform", "platform", "workspace", "workspace"]);
  assert.deepEqual(read.steps.map((step) => step.status), ["done", "unknown", "unknown", "attention", "unknown", "unknown", "done"]);
  assert.equal(read.steps[3].reason, "models reason");
  assert.deepEqual(read.steps.filter((step) => step.recommended).map((step) => step.key), ["sso", "roles"]);
  assert.deepEqual(read.workspace, { id: "ws-1", name: "ux-first-run" });
  assert.equal(readSetupStatus({ steps: "x" }), null);
  assert.ok(unknownSteps().every((step) => step.status === "unknown"));
});

test("a skipped recommended step is not open, stays listed and can be resumed; required steps cannot be skipped", () => {
  const steps = readSetupStatus(payload({ workspace: "done", connectors: "done", sources: "done", models: "done",
    sso: "open", roles: "open", agents: "open" })).steps;
  const skipped = applySkips(steps, new Set(["sso", "roles", "agents"]));
  assert.deepEqual(skipped.map((step) => step.status), ["done", "done", "done", "done", "skipped", "skipped", "open"]);
  assert.equal(skipped.length, 7);
  assert.deepEqual(setupSummary(skipped), { done: 4, total: 7, requiredOpen: 1 });
  assert.equal(setupProgressText(setupSummary(skipped)), "Setup: 4 of 7 done");
  const allRequiredDone = applySkips(readSetupStatus(payload({ workspace: "done", connectors: "done", sources: "done",
    models: "done", sso: "open", roles: "open", agents: "done" })).steps, new Set(["sso"]));
  assert.equal(setupProgressText(setupSummary(allRequiredDone)), null, "only recommended steps left: no reminder");
  assert.equal(setupProgressText(setupSummary(readSetupStatus(payload({ models: "attention" })).steps)), "Setup: 0 of 7 done");
});

test("skips are kept per person, versioned, and survive blocked storage", () => {
  const map = new Map();
  const store = { getItem: (key) => map.get(key) ?? null, setItem: (key, value) => map.set(key, value) };
  writeSkips(store, "u1", new Set(["sso"]));
  assert.deepEqual([...readSkips(store, "u1")], ["sso"]);
  assert.deepEqual([...readSkips(store, "u2")], []);
  assert.ok([...map.keys()][0].startsWith("octryx.setup.skipped.v1."));
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.deepEqual([...readSkips(broken, "u1")], []);
  writeSkips(broken, "u1", new Set(["sso"]));
});

test("every step has a help file with a benefit sentence and one link to a real page; the way back is marked", () => {
  for (const key of SETUP_STEP_KEYS) {
    const doc = parseHelpDoc(`/help/setup/${key}.md`, readFileSync(new URL(`../../help/setup/${key}.md`, import.meta.url), "utf8"));
    assert.ok(doc.title && doc.title !== key, key);
    const benefit = doc.body.split("\n").find((line) => line.trim() && !line.startsWith("#"));
    assert.ok(benefit && benefit.endsWith(".") && benefit.length < 160, `${key}: ${benefit}`);
    const links = [...doc.body.matchAll(/\]\((\/chat\?[^)]+)\)/g)].map((match) => match[1]);
    assert.equal(links.length, 1, key);
    const target = helpLinkTarget(links[0]);
    if (target.tab && target.area !== "knowledge") assert.equal(resolveAdminAreaForTab(target.tab), target.area, links[0]);
    const step = unknownSteps().find((entry) => entry.key === key);
    const href = stepHref(links[0], step, "ws-1");
    assert.match(href, /from=setup/);
    assert.equal(/workspace_id=ws-1/.test(href), step.scope === "workspace", href);
  }
});

test("the server's level and target win: a shared connection is a platform fact, Models opens Default & fallback", async () => {
  const { readSetupStatus, stepHref } = await import("../../src/chat/setup/setupGuideModel.ts");
  const status = readSetupStatus({ workspace: { id: "ws-1", name: "ux-first-run" }, steps: [
    { key: "connectors", status: "done", scope: "platform", reason: "Uses a shared connection of the platform." },
    { key: "models", status: "attention", scope: "platform", reason: "Claude Sonnet 5.5 is #1 but not cleared for data.", target: "modelOrder" },
  ] });
  const connectors = status.steps.find((step) => step.key === "connectors");
  assert.equal(connectors.scope, "platform");
  const models = status.steps.find((step) => step.key === "models");
  assert.equal(stepHref("/chat?area=admin&tab=providers", models, "ws-1"), "/chat?area=admin&tab=modelOrder&from=setup");
});

test("Archive and Delete say what differs", () => {
  const source = readFileSync(new URL("../../src/admin/components/AdminProjectsTab.tsx", import.meta.url), "utf8");
  assert.match(source, /Restore brings it back exactly as it was/);
  assert.match(source, /Knowledge sources are paused with their automatic\s+sync switched off/);
  assert.match(source, /To keep everything as it is, archive instead/);
});
