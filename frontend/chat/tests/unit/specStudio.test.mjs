// Spec Studio: the address, the live contrast and mock rules, and the choice group's keyboard logic.
// The backend decides again on every change (tests/test_spec_studio_*.py); these keep the page live and honest.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { nextChoice } from "../../src/layout/ChoiceGroup.ts";
import { runStatusLabel } from "../../src/chat/workflowRun/workflowRunStatus.ts";
import { specStudioAddress, specStudioHref } from "../../src/chat/specStudio/specStudioAddress.ts";
import { answerOf, approveState, contrast, contrastRows, corporateAssetUrl, describeElement, directionsOf, effectiveDesign, mockScale, mockVariables, onAccent, pinPosition, validRadius, valueMark } from "../../src/chat/specStudio/specStudioModel.ts";
import { normalizeHex } from "../../src/layout/ColorRow.ts";

// The real Studio data the backend tests use (Bench Coffee).
const CAF44 = JSON.parse(readFileSync(new URL("../../../../backend/tests/fixtures/spec_studio/caf44/studio.json", import.meta.url), "utf8"));

test("the Studio is a Work address with a run; render= names one screen of the mock", () => {
  assert.deepEqual(specStudioAddress("?area=work&work_view=spec_studio&run_id=r1"), { runId: "r1", render: null });
  assert.equal(specStudioAddress("?area=work&work_view=runs&run_id=r1"), null);
  assert.equal(specStudioAddress("?area=work&work_view=spec_studio"), null);
  assert.deepEqual(specStudioAddress("?area=work&work_view=spec_studio&run_id=r1&render=today&device=phone&theme=dark&version=2").render,
    { screen: "today", device: "phone", theme: "dark", data: "filled", version: 2 });
  assert.equal(specStudioHref("a b"), "/chat?area=work&work_view=spec_studio&run_id=a%20b");
});

test("contrast follows WCAG and the button text takes the stronger ink", () => {
  assert.equal(Math.round(contrast("#000000", "#FFFFFF") * 10) / 10, 21);
  assert.equal(onAccent("#8A4B2A"), "#FFFFFF");
  assert.equal(onAccent("#E0A06A"), "#1A1410");
  const design = effectiveDesign(CAF44, {}, null);
  assert.ok(contrastRows(design).every((row) => row.passes), "the CAF-44 tokens pass AA in light and dark");
  const weak = effectiveDesign(CAF44, { tokens: { dark: { muted: "#5A4A3E" } } }, null);
  assert.deepEqual(contrastRows(weak).filter((row) => !row.passes).map((row) => `${row.theme}:${row.pair}`), ["dark:Muted text on card"]);
});

test("the product owner's choices override the proposed direction, and a new direction starts from its own colours", () => {
  const chosen = effectiveDesign(CAF44, { direction: "barista", radius: 6, tokens: { light: { accent: "#7A3F20" } } }, null);
  assert.equal(chosen.name, "Barista Dark");
  assert.equal(chosen.radius, 6);
  assert.equal(chosen.light.accent, "#7A3F20");
  const vars = mockVariables(chosen, "dark");
  assert.equal(vars["--m-bg"], "#141416");
  assert.equal(vars["--m-r"], "6px");
  assert.equal(vars["--m-on-accent"], onAccent("#D08A55"));
});

test("a phone sees the whole desktop mock scaled down; 100 % shows it unscaled; a pin stays in the mock's own pixels", () => {
  assert.equal(mockScale(358, "desktop", false), 358 / 1280);
  assert.equal(mockScale(1400, "desktop", false), 1, "never scaled up");
  assert.equal(mockScale(358, "desktop", true), 1);
  const scale = 358 / 1280;
  assert.deepEqual(pinPosition(16 + 100 * scale, 200 + 400 * scale, { left: 16, top: 200 }, scale), { x: 100, y: 400 });
  assert.equal(describeElement("  Brazil   Cerrado ", "Heute"), "Brazil Cerrado");
  assert.equal(describeElement("", "Heute"), "Heute");
  assert.equal(describeElement("x".repeat(50), "Heute").length, 41);
});

test("colour and radius input is validated before it is saved", () => {
  assert.equal(normalizeHex("8a4b2a"), "#8A4B2A");
  assert.equal(normalizeHex("#abc"), "#AABBCC");
  assert.equal(normalizeHex("brown"), null);
  assert.equal(validRadius("12"), 12);
  assert.equal(validRadius("12.5"), null);
  assert.equal(validRadius(-1), null);
  assert.equal(validRadius(99), null);
});

test("an answer is the proposal until the product owner picks or writes another", () => {
  const question = CAF44.questions[0];
  assert.deepEqual(answerOf(question, {}), { value: "2", other: "" });
  assert.deepEqual(answerOf(question, { answers: { purge: { value: "24" } } }), { value: "24", other: "" });
  assert.deepEqual(answerOf(question, { answers: { purge: { other: "nach 6 h" } } }), { value: "", other: "nach 6 h" });
});

test("approval: open points block it, own changes go to revision, a frozen version shows who approved", () => {
  const payload = { open_points: [], needs_revision: false, frozen: false, awaiting_approval: true, approved: [] };
  assert.equal(approveState(payload).mode, "approve");
  assert.equal(approveState({ ...payload, awaiting_approval: false }).mode, "waiting");
  assert.equal(approveState({ ...payload, open_points: [{ text: "x" }] }).mode, "blocked");
  assert.equal(approveState({ ...payload, open_points: [{ text: "x" }], needs_revision: true }).mode, "revise");
  assert.equal(approveState({ ...payload, frozen: true, approved: [{ version: 1 }] }).mode, "frozen");
});

test("a choice group moves with the arrow keys and skips disabled choices", () => {
  const choices = [{ key: "light", label: "Light" }, { key: "dark", label: "Dark", disabled: true }, { key: "auto", label: "Auto" }];
  assert.equal(nextChoice(choices, "light", "ArrowRight"), "auto");
  assert.equal(nextChoice(choices, "light", "ArrowLeft"), "auto");
  assert.equal(nextChoice(choices, "auto", "ArrowDown"), "light");
  assert.equal(nextChoice(choices, "light", "Enter"), null);
});

test("a run whose decisions gate waits for the product owner says so in the card and in the run lists", () => {
  const base = { status: "waiting", waiting_kind: "awaiting_confirmation", pause_reason: null, outcome: null };
  assert.equal(runStatusLabel({ ...base, waiting: { reason: "spec_approval" } }), "Waiting for spec approval");
  assert.equal(runStatusLabel({ ...base, waiting_reason: "spec_approval" }), "Waiting for spec approval");
  assert.equal(runStatusLabel(base), "Waiting for your confirmation");
  assert.equal(runStatusLabel({ ...base, status: "running", waiting_reason: "spec_approval" }), "Running");
});

// The Corporate Identity is preselected, the spec's directions are the alternatives.
const CORPORATE = {
  profile_id: "house", profile_name: "Example Brand", source: "installation", locks: ["light.accent"], hash: "h",
  sources: { "light.accent": "ci", "light.bg": "ci", "dark.accent": "derived" }, logo: "assets/logo.png",
  icons: { cup: "icons/general/cup.svg" },
  direction: { id: "corporate", name: "Corporate: Example Brand", hint: "Your corporate identity.",
    light: { bg: "#FFFFFF", surface: "#F1F3F6", text: "#14213D", muted: "#4A5568", accent: "#0B5FA5" },
    dark: { bg: "#121722", surface: "#1A2130", text: "#FFFFFF", muted: "#A9B1BF", accent: "#5AA0E0" },
    fonts: { head: "Georgia, system-ui, sans-serif", body: "Verdana, system-ui, sans-serif", mono: "ui-monospace, monospace" },
    radius: 8 },
};

test("the company's look is preselected; the spec's directions stay as alternatives", () => {
  assert.deepEqual(directionsOf(CAF44, CORPORATE).map((d) => d.id), ["corporate", ...CAF44.design.directions.map((d) => d.id)]);
  const preselected = effectiveDesign(CAF44, {}, null, CORPORATE);
  assert.equal(preselected.direction, "corporate");
  assert.equal(preselected.light.accent, "#0B5FA5");
  assert.equal(effectiveDesign(CAF44, { direction: "crema" }, null, CORPORATE).direction, "crema");
  assert.equal(effectiveDesign(CAF44, {}, null, null).direction, CAF44.design.proposed);  // no CI:
});

test("a value shows where it comes from and a lock, only on the corporate direction", () => {
  const onCorporate = effectiveDesign(CAF44, {}, null, CORPORATE);
  assert.deepEqual(valueMark({ corporate: CORPORATE }, onCorporate, "light.accent"), { source: "ci", locked: true });
  assert.deepEqual(valueMark({ corporate: CORPORATE }, onCorporate, "dark.accent"), { source: "derived", locked: false });
  const alternative = effectiveDesign(CAF44, { direction: "crema" }, null, CORPORATE);
  assert.deepEqual(valueMark({ corporate: CORPORATE }, alternative, "light.accent"), { source: null, locked: false });
  assert.equal(corporateAssetUrl("r 1", "icons/a b.svg"), "/api/v1/workflow-runs/r%201/spec-studio/corporate-asset?path=icons%2Fa%20b.svg");
});

test("a missing deviation reason is the product owner's point: no revision, the reason is asked for", () => {
  const point = { section: "design", target: "deviation:light.accent", text: "light.accent differs …", by: "product_owner" };
  const payload = { frozen: false, needs_revision: false, awaiting_approval: true, approved: [], open_points: [point] };
  const state = approveState(payload);
  assert.equal(state.mode, "blocked");
  assert.match(state.reason, /give the reason for each deviation/);
  const mixed = approveState({ ...payload, open_points: [point, { section: "rules", target: "R1", text: "x" }] });
  assert.match(mixed.reason, /the spec phase fixes/);
});

test("the Workspace select names the company default and a lock toggles one path", async () => {
  const { companyDefaultLabel, toggleLock, LOCK_GROUPS } = await import("../../src/admin/components/corpIdentity/corpStudioLocksModel.ts");
  assert.equal(companyDefaultLabel([{ id: "a", name: "House", is_default: true }, { id: "b", name: "Product" }]), "Company default (House)");
  assert.equal(companyDefaultLabel([]), "Company default (none yet)");
  assert.deepEqual(toggleLock(["light.accent"], "fonts.head", true), ["fonts.head", "light.accent"]);
  assert.deepEqual(toggleLock(["fonts.head", "light.accent"], "light.accent", false), ["fonts.head"]);
  // Every lockable path of the backend (corp_identity/workspace.LOCKABLE) is offered once.
  assert.equal(new Set(LOCK_GROUPS.flatMap((group) => group.paths.map((p) => p.path))).size, 21);
});

test("people read token paths as names: deviations, open points and locks", async () => {
  const { lockLabel, deviationPointText } = await import("../../src/admin/components/corpIdentity/corpStudioLocksModel.ts");
  assert.equal(lockLabel("light.accent"), "Main action (light)");
  assert.equal(lockLabel("dark.muted"), "Muted text (dark)");
  assert.equal(lockLabel("fonts.head"), "Heading font");
  assert.equal(lockLabel("direction"), "Style direction");
  assert.equal(lockLabel("spacing.unit"), "spacing.unit");  // unknown: the path itself
  assert.equal(deviationPointText("deviation:light.accent", "light.accent differs …"), "Main action (light) differs from Corporate: give the reason.");
  assert.equal(deviationPointText("R1", "R1 needs an example."), "R1 needs an example.");
});
