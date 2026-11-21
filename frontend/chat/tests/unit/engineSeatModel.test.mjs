// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/engineSeatModel.test.mjs
//
// The phone's engine/route/model line, the person's seat status and the Workspace's seat switches (read-only), as the
// phone shows them. Nothing a payload lacks is guessed.
import { readOpenSessions } from "../../src/mobile/mobileTerminalSessions.ts";
import { readRunRows } from "../../src/mobile/mobileRuns.ts";
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  deviceRoutes,
  readSeatStatus,
  resetText,
  runLine,
  runLineRest,
  runLineText,
  seatRules,
  seatSignInText,
  threadRunLineText,
  workflowRunLine,
} from "../../src/mobile/engineSeatModel.ts";

test("the run line: engine (none = Claude Code), route from the profile, readable model; unknowns drop out", () => {
  assert.equal(runLineText(runLine({ engine: "codex", profile: "seat", model: "gpt-5-codex" })), "Codex · Own subscription · GPT 5 Codex");
  assert.equal(runLineText(runLine({ engine: null, profile: "governed", model: "claude-opus-5-5" })), "Claude Code · Company model · Claude Opus 5.5");
  // A live session reports no model; an unknown profile is not shown as a raw id.
  assert.equal(runLineText(runLine({ engine: "codex", profile: "work" }), "shop", "MacBook"), "Codex · shop · MacBook");
  assert.equal(runLineText(runLine({ profile: "local:team" })), "Claude Code · Own subscription");
  // The header form leaves the engine to its tag.
  assert.equal(runLineRest(runLine({ engine: "codex", profile: "seat", model: "" }), "MacBook"), "Own subscription · MacBook");
});

test("a workflow run's route comes from the server's route; a run with neither engine nor route has no line", () => {
  const rows = readRunRows({ runs: [
    { id: "r1", status: "running", engine: "codex", route: "own_subscription" },
    { id: "r2", status: "running", engine: "claude_code", route: "company_model" },
    { id: "r3", status: "running", engine: null, route: null },
  ] });
  assert.deepEqual(rows.map((row) => row.line && runLineText(row.line)), [
    "Codex · Own subscription", "Claude Code · Company model", null]);
  // An unknown route word is not shown raw.
  assert.equal(runLineText(workflowRunLine({ engine: "codex", route: "something_new" })), "Codex");
});

test("a chat list row: the device chat's engine, route and model, then the Mac; a row without them only the Mac", () => {
  assert.equal(threadRunLineText({ kind: "device", deviceName: "MacBook Pro", engine: "codex", profile: "seat", model: "gpt-5-codex" }),
    "Codex · Own subscription · GPT 5 Codex · MacBook Pro");
  assert.equal(threadRunLineText({ kind: "device", deviceName: "MacBook Pro", engine: "claude_code", profile: null, model: null }),
    "Claude Code · MacBook Pro");
  assert.equal(threadRunLineText({ kind: "device", deviceName: "MacBook Pro" }), "MacBook Pro");
  assert.equal(threadRunLineText(null), "");
});

test("an open terminal session carries its engine, so a Codex session never reads as Claude Code", () => {
  const [codex, claude] = readOpenSessions({ items: [
    { id: "a", profile: "seat", engine: "codex", model: "gpt-5-codex" },
    { id: "b", profile: "governed", engine: "claude_code" },
  ] });
  assert.equal(runLineText(runLine(codex)), "Codex · Own subscription · GPT 5 Codex");
  assert.equal(runLineText(runLine(claude)), "Claude Code · Company model");
});

const mac = (name, connected, seatLogin, codexSeatLogin = false) =>
  ({ name, connected, seatLogin, codexSeatLogin, profiles: ["governed", "seat"] });

test("seat status: signed in only on an online Mac; the allowance windows only when the server reported them", () => {
  const usage = { seat_allowance: { five_hour_pct: 42.4, five_hour_resets_at: "2026-11-15T14:30:00Z", seven_day_pct: 81,
    seven_day_resets_at: null, updated_at: "2026-11-15T12:00:00Z" } };
  const status = readSeatStatus([mac("MacBook Pro", true, true), mac("Studio", false, true)], usage);
  assert.equal(seatSignInText(status), "Signed in on MacBook Pro"); // the offline Studio's last login is not known
  assert.deepEqual(status.windows.map((w) => [w.key, w.percent, w.resetsAt]), [["5h", 42, "2026-11-15T14:30:00Z"], ["7d", 81, null]]);
  assert.equal(status.updatedAt, "2026-11-15T12:00:00Z");

  const without = readSeatStatus([mac("MacBook Pro", true, false)], { seat_allowance: null });
  assert.equal(seatSignInText(without), "Not signed in");
  assert.deepEqual(without.windows, []);
  assert.equal(seatSignInText(readSeatStatus([mac("Studio", false, true)], null)), "No Mac online");
  assert.equal(readSeatStatus(null, null).signedIn, null);
});

test("the Codex seat: its own sign-in and the codex_seat_allowance windows, apart from Claude's", () => {
  const usage = { seat_allowance: null, codex_seat_allowance: { five_hour_pct: 12, five_hour_resets_at: "2026-11-15T14:30:00Z",
    seven_day_pct: 90.6, seven_day_resets_at: "2026-11-18T08:00:00Z", updated_at: "2026-11-15T12:00:00Z" } };
  const macs = [mac("MacBook Pro", true, false, true)];
  const codex = readSeatStatus(macs, usage, "codex");
  assert.equal(seatSignInText(codex), "Signed in on MacBook Pro");
  assert.deepEqual(codex.windows.map((w) => [w.key, w.percent]), [["5h", 12], ["7d", 91]]);
  const claude = readSeatStatus(macs, usage);
  assert.equal(seatSignInText(claude), "Not signed in");
  assert.deepEqual(claude.windows, []);
  // Absent (not sent, or no Codex seat run yet): no windows.
  assert.deepEqual(readSeatStatus(macs, { seat_allowance: null }, "codex").windows, []);
});

test("a Mac's routes say whether its seat is signed in, only while it is online", () => {
  assert.equal(deviceRoutes(mac("A", true, true)), "Company model · Own subscription (signed in)");
  assert.equal(deviceRoutes(mac("A", true, false)), "Company model · Own subscription (not signed in)");
  assert.equal(deviceRoutes(mac("A", false, false)), "Company model · Own subscription");
  assert.equal(deviceRoutes(mac("A", true, true, true)), "Company model · Own subscription (Claude and Codex signed in)");
  assert.equal(deviceRoutes(mac("A", true, false, true)), "Company model · Own subscription (Codex signed in)");
  assert.equal(deviceRoutes({ profiles: ["governed"], connected: true, seatLogin: false, codexSeatLogin: false }), "Company model");
});

test("Workspace seat switches from seat-mode: allowed, forbidden, and allowed but not in effect", () => {
  const rules = seatRules({ seat_mode: "allowed", in_effect: false, reason: "seat_classification_too_sensitive",
    codex_seat_mode: "forbidden", codex_in_effect: false, codex_reason: "codex_seat_mode_forbidden" });
  assert.deepEqual(rules.map((r) => [r.label, r.value]), [
    ["Claude subscription (seat)", "Allowed"],
    ["Codex with your own ChatGPT subscription", "Forbidden"],
  ]);
  assert.equal(rules[0].note, "Not in effect: the data classification is too sensitive for them.");
  assert.equal(rules[1].note, null);
  const both = seatRules({ seat_mode: "allowed", in_effect: true, codex_seat_mode: "allowed", codex_in_effect: true });
  assert.deepEqual(both.map((r) => [r.value, r.note]), [["Allowed", null], ["Allowed", null]]);
});

test("seat-mode read directly: an unreadable answer leaves both switches unknown, never guessed", () => {
  assert.deepEqual(seatRules(null).map((r) => r.value), ["Unknown", "Unknown"]);
  assert.deepEqual(seatRules({ seat_mode: "forbidden" }).map((r) => r.value), ["Forbidden", "Unknown"]);
});

test("a reset today shows the time, a later one the weekday too; none shows nothing", () => {
  const now = new Date(2026, 10, 15, 9, 0);
  const today = new Date(2026, 10, 15, 14, 30);
  const later = new Date(2026, 10, 18, 14, 30);
  const time = today.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  assert.equal(resetText(today.toISOString(), now), time);
  assert.equal(resetText(later.toISOString(), now), `${later.toLocaleDateString([], { weekday: "short" })} ${time}`);
  assert.equal(resetText(null, now), "");
});
