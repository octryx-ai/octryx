// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/seatPolicySettings.test.mjs
//
// The three seat keys under the seat switches in the Data classification card (requires_governed_routing,
// seat_models, seat_allows_governed_models): the stored values as read, the save bodies that name only their own
// key, the model list rules at the field (the backend limits), the edit rules, the refusals in words, and the audit
// rows that name which seat setting changed from and to what.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allowsGovernedBody, canRemoveSeatModel, readSeatPolicySettings, requiresGovernedBody, seatFlagValueText,
  seatModelProblem, seatModelsBody, seatModelsValueText, seatSettingErrorText, seatSettingsDisabled, withSeatModel,
  withoutSeatModel, seatBoundLocks, invalidSettingWarnings, seatFieldOfError,
} from "../../src/admin/components/dataClassification/seatPolicyModel.ts";
import { auditChangeLabel, auditDiffLines } from "../../src/admin/components/observability/auditModel.ts";

const ANSWER = {
  seat_mode: "allowed", requires_governed_routing: false, seat_models: ["claude-sonnet-5", "claude-opus-5-5"],
  seat_models_default: ["claude-sonnet-5", "claude-opus-5-5"], seat_models_limits: { max_models: 20, max_model_id_chars: 100 },
  seat_allows_governed_models: false, can_edit: true, can_loosen: true, invalid_settings: [],
};
const LIMITS = { maxModels: 20, maxModelIdChars: 100 };

// A saved classification whose effects allow seat sessions, or block them (confidential).
const workspace = (canEdit, blocked = false) => ({
  canEdit, effective: blocked ? "confidential" : "internal",
  effects: { seatModeAllowed: !blocked, seatModeReason: blocked ? "seat_classification_too_sensitive" : null },
});

test("the stored values are read as the server answers them; missing keys are unknown, not off", () => {
  const settings = readSeatPolicySettings(ANSWER);
  assert.deepEqual(settings, {
    requiresGoverned: false, models: ["claude-sonnet-5", "claude-opus-5-5"],
    defaultModels: ["claude-sonnet-5", "claude-opus-5-5"], limits: LIMITS, allowsGoverned: false, canLoosen: true, invalid: [],
  });
  assert.equal(seatModelsValueText(settings), "Default");
  assert.equal(seatModelsValueText({ ...settings, models: ["claude-sonnet-5"] }), "Custom");
  assert.equal(seatFlagValueText(false), "Off (default)");
  assert.equal(seatFlagValueText(true), "On");
  const old = readSeatPolicySettings({ seat_mode: "allowed" });
  assert.deepEqual([old.requiresGoverned, old.models, old.allowsGoverned], [null, null, null]);
  assert.equal(seatFlagValueText(old.requiresGoverned), "Unknown");
  assert.deepEqual(old.limits, LIMITS, "the backend limits apply when the answer does not carry them");
});

test("each save body names only its own key, so the server keeps every other policy key", () => {
  assert.deepEqual(requiresGovernedBody(true), { requires_governed_routing: true });
  assert.deepEqual(allowsGovernedBody(false), { seat_allows_governed_models: false });
  const models = withSeatModel(["claude-sonnet-5"], "  claude-haiku-5 ");
  assert.deepEqual(seatModelsBody(models), { seat_models: ["claude-sonnet-5", "claude-haiku-5"] });
  assert.deepEqual(withoutSeatModel(models, "claude-sonnet-5"), ["claude-haiku-5"]);
});

test("the model list enforces the backend limits at the field", () => {
  const list = ["claude-sonnet-5"];
  assert.equal(seatModelProblem("claude-haiku-5", list, LIMITS), null);
  assert.equal(seatModelProblem("us.anthropic.claude-haiku-5:0[1m]", list, LIMITS), null, "the backend's . _ : - [ ] are allowed");
  assert.equal(seatModelProblem("x".repeat(100), list, LIMITS), null);
  assert.match(seatModelProblem("x".repeat(101), list, LIMITS), /at most 100 characters/);
  assert.match(seatModelProblem("claude haiku", list, LIMITS), /no spaces/);
  assert.match(seatModelProblem("claude/haiku", list, LIMITS), /only letters, digits/);
  assert.match(seatModelProblem("   ", list, LIMITS), /Enter a model id/);
  assert.match(seatModelProblem("claude-sonnet-5", list, LIMITS), /already in the list/);
  const full = Array.from({ length: 20 }, (_, index) => `m${index}`);
  assert.match(seatModelProblem("one-more", full, LIMITS), /at most 20 models/);
  assert.equal(canRemoveSeatModel(["claude-sonnet-5"]), false, "an empty list is refused, so the last model stays");
  assert.equal(canRemoveSeatModel(["a", "b"]), true);
});

test("members see the settings read-only; only loosening company models is blocked while the classification blocks seats", () => {
  const settings = readSeatPolicySettings(ANSWER);
  const all = (value) => ({ requiresGoverned: value, models: value, addModels: value, allowsGoverned: value });
  assert.deepEqual(seatSettingsDisabled(workspace(false), settings), all(true), "a member, even a platform admin, reads only");
  assert.deepEqual(seatSettingsDisabled(workspace(true), settings), all(false));
  const blocked = seatSettingsDisabled(workspace(true, true), settings);
  assert.equal(blocked.allowsGoverned, true, "turning company models on is blocked");
  assert.equal(seatSettingsDisabled(workspace(true, true), { ...settings, allowsGoverned: true }).allowsGoverned, false,
    "turning them off always works");
  assert.equal(seatSettingsDisabled(workspace(true), readSeatPolicySettings({})).requiresGoverned, true, "an unknown value is not editable");
});

test("without the server's can_loosen (Workspace admin or owner) only tightening is open", () => {
  const settings = readSeatPolicySettings({ ...ANSWER, can_loosen: false }); // governed routing off, company models off
  assert.equal(readSeatPolicySettings({ ...ANSWER, can_loosen: undefined }).canLoosen, false, "an unstated right is not assumed");
  const owner = seatSettingsDisabled(workspace(true), settings);
  assert.equal(owner.requiresGoverned, false, "switching 'Only company models' on tightens: open to the owner");
  assert.equal(owner.allowsGoverned, true, "allowing company models in seat loosens");
  assert.equal(owner.addModels, true, "adding a seat model loosens");
  assert.equal(owner.models, false, "removing a seat model tightens");
  const governedOn = seatSettingsDisabled(workspace(true), { ...settings, requiresGoverned: true, allowsGoverned: true });
  assert.equal(governedOn.requiresGoverned, true, "switching it off again needs a platform admin");
  assert.equal(governedOn.allowsGoverned, false, "switching company models off tightens");

  assert.deepEqual(seatBoundLocks(false, { seatMode: "forbidden", codexMode: "allowed", requiresGoverned: null, allowsGoverned: null }),
    { seatMode: true, codexMode: false, requiresGoverned: false, allowsGoverned: true, addModels: true },
    "allowing a seat mode loosens; forbidding an allowed one tightens");
  assert.deepEqual(seatBoundLocks(true, { seatMode: "forbidden", codexMode: "forbidden", requiresGoverned: true, allowsGoverned: false }),
    { seatMode: false, codexMode: false, requiresGoverned: false, allowsGoverned: false, addModels: false }, "a platform admin may do all");
});

test("a stored invalid value is a warning, not the default; a refusal lands at the field its path names", () => {
  const settings = readSeatPolicySettings({ ...ANSWER, seat_models: null, invalid_settings: ["seat_models", "codex_seat_mode"] });
  assert.equal(settings.models, null);
  assert.deepEqual(invalidSettingWarnings(settings.invalid), [
    "The stored value for the seat model list is not valid; a platform admin should set it again.",
    "The stored value for the Codex seat is not valid; a platform admin should set it again.",
  ]);
  const refused = { status: 403, code: "platform_admin_required", detail: { code: "platform_admin_required", path: "seat_allows_governed_models" } };
  assert.equal(seatFieldOfError(refused, "models"), "allowsGoverned");
  assert.equal(seatFieldOfError({ status: 422, code: "invalid_list" }, "models"), "models");
});

test("a refused save reads as words at the field", () => {
  assert.equal(seatSettingErrorText({ status: 403 }, "the seat model list", LIMITS),
    "Not saved: only Workspace admins and owners can change the seat model list.");
  assert.equal(seatSettingErrorText({ status: 403, code: "platform_admin_required" }, "the seat model list", LIMITS),
    "Not saved: only a platform admin can change this.");
  assert.equal(seatSettingErrorText({ status: 422, code: "unknown_setting" }, "x", LIMITS), "Not saved: the server does not know this setting.");
  assert.equal(seatSettingErrorText({ status: 422, code: "invalid_list" }, "the seat model list", LIMITS),
    "Not saved: the list needs 1 to 20 model ids.");
  assert.match(seatSettingErrorText({ status: 422, code: "invalid_model_id" }, "x", LIMITS), /1 to 100 characters/);
  assert.equal(seatSettingErrorText({ status: 422, code: "invalid_flag" }, "x", LIMITS), "Not saved: the value must be on or off.");
  assert.match(seatSettingErrorText({ status: 422, code: "agent_gateway_policy_invalid" }, "x", LIMITS), /stored agent gateway policy/);
});

test("the audit row names which seat setting changed, from and to which value", () => {
  const action = "admin.agent_gateway.seat_mode_updated";
  const codex = { codex_seat_mode: "allowed", before: { codex_seat_mode: "forbidden" }, after: { codex_seat_mode: "allowed" } };
  assert.equal(auditChangeLabel(action, codex), "Codex seat: Forbidden → Allowed");
  assert.equal(auditChangeLabel(action, { seat_mode: "forbidden", before: { seat_mode: "allowed" }, after: { seat_mode: "forbidden" } }),
    "Claude seat: Allowed → Forbidden");
  assert.equal(auditChangeLabel(action, { seat_mode: "allowed", before: { seat_mode: null }, after: { seat_mode: "allowed" } }),
    "Claude seat: not set → Allowed", "a setting saved for the first time");
  assert.equal(auditChangeLabel(action, { requires_governed_routing: true, before: { requires_governed_routing: false },
    after: { requires_governed_routing: true } }), "Only company models: Off → On");
  assert.equal(auditChangeLabel(action, { seat_models: ["a", "c"], before: { seat_models: ["a", "b"] }, after: { seat_models: ["a", "c"] } }),
    "Claude seat models: added c; removed b");
  assert.equal(auditChangeLabel(action, {}), "Seat setting changed");
  assert.equal(auditChangeLabel("admin.project_config.updated", codex), "Project config updated", "other events ignore details");
  assert.deepEqual(auditDiffLines(codex, action), [
    { kind: "del", text: "- Codex seat: Forbidden" }, { kind: "add", text: "+ Codex seat: Allowed" }]);
  assert.deepEqual(auditDiffLines(codex), [
    { kind: "del", text: "- codex_seat_mode: forbidden" }, { kind: "add", text: "+ codex_seat_mode: allowed" }]);
});
