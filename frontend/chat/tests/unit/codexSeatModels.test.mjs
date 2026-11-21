// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codexSeatModels.test.mjs
//
// The Codex seat's model list (codex_seat_models) under the Codex seat switch: "all" (no list) vs. a list as
// read from the seat route, the save body naming only its own key, the loosen/tighten rule per change (the same rule as
// backend workspace_settings/bounds.py), which steps a Workspace admin vs. a platform admin may take, and refusals.

import assert from "node:assert/strict";
import test from "node:test";

import {
  codexModelsActions, codexModelsChangeLoosens, codexModelsValueText, codexSeatModelsBody, readCodexSeatModels,
} from "../../src/admin/components/dataClassification/codexSeatModelsModel.ts";
import { seatSettingErrorText } from "../../src/admin/components/dataClassification/seatPolicyModel.ts";

const LIMITS = { maxModels: 20, maxModelIdChars: 100 };

test("null is every Codex model; a list is a list; missing or invalid is unknown, never 'all'", () => {
  assert.deepEqual(readCodexSeatModels({ codex_seat_models: null, invalid_settings: [] }), { kind: "all" });
  assert.deepEqual(readCodexSeatModels({ codex_seat_models: ["gpt-5.5"] }), { kind: "list", models: ["gpt-5.5"] });
  assert.deepEqual(readCodexSeatModels({ seat_mode: "allowed" }), { kind: "unknown" });
  assert.deepEqual(readCodexSeatModels({ codex_seat_models: null, invalid_settings: ["codex_seat_models"] }), { kind: "unknown" });
  assert.equal(codexModelsValueText({ kind: "all" }), "Default");
  assert.equal(codexModelsValueText({ kind: "list", models: ["gpt-5.5"] }), "Custom");
});

test("the body names only codex_seat_models; null goes back to every model", () => {
  assert.deepEqual(codexSeatModelsBody(["gpt-5.5"]), { codex_seat_models: ["gpt-5.5"] });
  assert.deepEqual(codexSeatModelsBody(null), { codex_seat_models: null });
});

test("restricting from all and removing tighten; adding or going back to all loosens", () => {
  assert.equal(codexModelsChangeLoosens(null, ["gpt-5.5"]), false);
  assert.equal(codexModelsChangeLoosens(["gpt-5.5", "gpt-5.5-mini"], ["gpt-5.5"]), false);
  assert.equal(codexModelsChangeLoosens(["gpt-5.5"], ["gpt-5.5", "gpt-5.5-mini"]), true);
  assert.equal(codexModelsChangeLoosens(["gpt-5.5"], null), true);
});

test("a Workspace admin may restrict and remove; only can_loosen adds or allows all; members only read", () => {
  const list = { kind: "list", models: ["gpt-5.5"] };
  assert.deepEqual(codexModelsActions({ kind: "all" }, true, false), { restrict: true, add: false, remove: false, allowAll: false });
  assert.deepEqual(codexModelsActions(list, true, false), { restrict: false, add: false, remove: true, allowAll: false });
  assert.deepEqual(codexModelsActions(list, true, true), { restrict: false, add: true, remove: true, allowAll: true });
  assert.deepEqual(codexModelsActions(list, false, true), { restrict: false, add: false, remove: false, allowAll: false });
  assert.deepEqual(codexModelsActions({ kind: "unknown" }, true, true), { restrict: false, add: false, remove: false, allowAll: false });
});

test("refusals read as words: the platform-admin bound and an invalid list", () => {
  assert.equal(seatSettingErrorText({ status: 403, code: "platform_admin_required" }, "the Codex model list", LIMITS),
    "Not saved: only a platform admin can change this.");
  assert.equal(seatSettingErrorText({ status: 422, code: "invalid_list" }, "the Codex model list", LIMITS),
    "Not saved: the list needs 1 to 20 model ids.");
});
