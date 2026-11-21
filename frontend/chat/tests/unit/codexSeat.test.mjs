// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codexSeat.test.mjs
//
// The Codex seat switch (`codex_seat_mode`, backend) next to the Claude seat switch in the Data classification
// card: the value mapping, the save body that names only its own key, the hint when the Codex engine is not allowed,
// and the refusal reason in words (card and device jobs).

import assert from "node:assert/strict";
import test from "node:test";

import {
  codexEngineHint, codexSeatBody, readCodexSeat,
} from "../../src/admin/components/dataClassification/codexSeatModel.ts";
import { classificationSaveErrorText } from "../../src/admin/components/dataClassification/dataClassificationModel.ts";
import { seatReasonText } from "../../src/admin/components/dataClassification/dataClassificationSeat.ts";
import { reasonText as jobReasonText } from "../../src/chat/devices/deviceJobsModel.ts";

test("the Codex switch reads its own key, never the Claude seat's", () => {
  const seat = readCodexSeat({ seat_mode: "allowed", in_effect: true, codex_seat_mode: "forbidden", codex_in_effect: false,
    codex_reason: "codex_seat_mode_forbidden" });
  assert.deepEqual(seat, { mode: "forbidden", inEffect: false, reason: "codex_seat_mode_forbidden" });
  assert.equal(readCodexSeat({ seat_mode: "allowed" }).mode, null, "an answer without the key is unknown, not allowed");
  assert.equal(readCodexSeat({ codex_seat_mode: "sometimes" }).mode, null);
});

test("the save body names only codex_seat_mode, so the other policy keys stay untouched", () => {
  assert.deepEqual(codexSeatBody(true), { codex_seat_mode: "allowed" });
  assert.deepEqual(codexSeatBody(false), { codex_seat_mode: "forbidden" });
});

test("a hint appears only when the Workspace's engines are known and Codex is not among them", () => {
  assert.match(codexEngineHint(["claude_code"]), /Codex is not an allowed coding engine/);
  assert.equal(codexEngineHint(["claude_code", "codex"]), null);
  assert.equal(codexEngineHint(null), null, "unknown engines give no hint");
});

test("the Codex refusal and its save errors read as words", () => {
  assert.equal(seatReasonText("codex_seat_mode_forbidden"), "this Workspace does not allow Codex with a ChatGPT subscription");
  assert.equal(jobReasonText("codex_seat_mode_forbidden"), "the Workspace does not allow Codex with a ChatGPT subscription");
  assert.equal(classificationSaveErrorText({ status: 403 }, "the Codex seat setting"),
    "Not saved: only Workspace admins and owners can change the Codex seat setting.");
  assert.match(classificationSaveErrorText({ status: 422, code: "agent_gateway_policy_invalid" }), /stored agent gateway policy .* is invalid/);
});
