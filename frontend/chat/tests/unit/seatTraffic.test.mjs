// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/seatTraffic.test.mjs
//
// Seat traffic: the platform switch's state, body, confirmation and refusals; the run's seat events as
// history lines (field names only); the audit labels.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  readSeatTrafficSetting,
  seatTrafficBody,
  seatTrafficConfirmText,
  seatTrafficLoadOutcome,
  seatTrafficSaveError,
} from "../../src/admin/components/seatTraffic/seatTrafficModel.ts";
import { seatEventLine } from "../../src/chat/workflowRun/seatEventsModel.ts";
import { runHistory } from "../../src/chat/workflowRun/runHistoryModel.ts";
import { auditChangeLabel } from "../../src/admin/components/observability/auditModel.ts";

test("the switch reads device unless the server says gateway; only can_edit true makes it editable", () => {
  assert.deepEqual(readSeatTrafficSetting({ seat_traffic: "gateway", can_edit: true }), { mode: "gateway", canEdit: true });
  assert.deepEqual(readSeatTrafficSetting({ seat_traffic: "device" }), { mode: "device", canEdit: false });
  assert.deepEqual(readSeatTrafficSetting({ seat_traffic: "other", can_edit: "yes" }), { mode: "device", canEdit: false });
  assert.equal(readSeatTrafficSetting({ permissive_only: true }), null);
  assert.equal(readSeatTrafficSetting(null), null);
});

test("the PUT sends exactly the one field the server accepts", () => {
  assert.deepEqual(seatTrafficBody("gateway"), { seat_traffic: "gateway" });
});

test("the confirmation names the target in words, says it affects every seat session and has no fallback", () => {
  const text = seatTrafficConfirmText("gateway");
  assert.match(text, /"Through the platform gateway"/);
  assert.match(text, /every seat session/);
  assert.match(text, /no automatic fallback/);
  assert.match(seatTrafficConfirmText("device"), /"From the person's device"/);
});

test("a forbidden GET hides the card; 403 and 422 refusals read in words", () => {
  assert.equal(seatTrafficLoadOutcome(403), "hidden");
  assert.equal(seatTrafficLoadOutcome(500), "problem");
  assert.match(seatTrafficSaveError(403, null), /only platform admins/);
  assert.match(seatTrafficSaveError(422, { detail: { errors: [{ code: "invalid_seat_traffic" }] } }), /device or gateway/);
  assert.match(seatTrafficSaveError(422, { detail: { errors: [{ code: "unknown_setting" }] } }), /does not know this setting/);
  assert.equal(seatTrafficSaveError(500, null), "Not saved: the request failed.");
});

test("a report mismatch lists only field names in words, never values", () => {
  const line = seatEventLine("seat_report_mismatch", { fields: ["model", "usage", "response_id"], model: "gpt-5-codex",
    session_id: "s1" });
  assert.equal(line.text, "The device's report did not match the admitted call: model, tokens, response id");
  assert.equal(line.tone, "attention");
  assert.doesNotMatch(line.text, /gpt-5|s1/);
  assert.equal(seatEventLine("seat_report_mismatch", { fields: [{ v: 1 }] }).text,
    "The device's report did not match the admitted call");
});

test("a call without report and both events in the run history; other kinds are not seat lines", () => {
  assert.equal(seatEventLine("seat_call_without_report", { model: "m" }).text,
    "A seat call was admitted but the device sent no report");
  assert.equal(seatEventLine("run_started", {}), null);
  const history = runHistory([
    { id: "1", kind: "seat_report_mismatch", node_id: null, detail: { fields: ["model"] }, actor_id: null, created_at: null },
    { id: "2", kind: "seat_call_without_report", node_id: null, detail: {}, actor_id: null, created_at: null },
  ], [], () => "");
  assert.deepEqual(history.map((entry) => [entry.title, entry.auto, entry.tone]),
    [["Seat call", "Needs a look", "attention"], ["Seat call", "Needs a look", "attention"]]);
});

test("audit: the switch and the seat events without a run have their own words", () => {
  assert.equal(auditChangeLabel("admin.agent_gateway.seat_traffic_updated"), "Seat traffic changed");
  assert.equal(auditChangeLabel("model_gateway.codex_seat.seat_report_mismatch"), "Seat call report did not match");
  assert.equal(auditChangeLabel("model_gateway.codex_seat.seat_call_without_report"), "Seat call without report");
});
