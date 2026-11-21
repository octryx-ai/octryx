// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/schedulerScheduleModel.test.mjs
//
// Guided scheduler authoring model: guided modes compile to name-based cron with bounded
// choices, a stored expression opens guided only on an exact round-trip (else Custom, verbatim),
// and the save gate only lets a new or changed expression through with a valid, current preview.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HOUR_STEPS,
  MINUTE_STEPS,
  compileGuided,
  formatRunTime,
  initialSchedule,
  recognizeSchedule,
  scheduleSubmitGate,
} from "../../src/admin/components/scheduler/scheduleModel.ts";

test("guided modes compile to cron with bounded steps and weekday names", () => {
  assert.deepEqual([...MINUTE_STEPS], [5, 10, 15, 20, 30]);
  assert.deepEqual([...HOUR_STEPS], [1, 2, 3, 4, 6, 8, 12]);
  assert.equal(compileGuided({ mode: "minutes", every: 15 }), "*/15 * * * *");
  assert.equal(compileGuided({ mode: "minutes", every: 7 }), "", "only the offered steps compile");
  assert.equal(compileGuided({ mode: "hours", every: 6 }), "0 */6 * * *");
  assert.equal(compileGuided({ mode: "hours", every: 5 }), "");
  assert.equal(compileGuided({ mode: "daily", time: "07:05" }), "5 7 * * *");
  assert.equal(compileGuided({ mode: "daily", time: "" }), "");
  const weekdays = (days) => compileGuided({ mode: "weekdays", days, time: "09:00" });
  assert.equal(weekdays(["fri", "mon", "tue", "wed", "thu"]), "0 9 * * mon-fri");
  assert.equal(weekdays(["sun", "sat"]), "0 9 * * sat,sun");
  assert.equal(weekdays(["mon", "wed", "fri"]), "0 9 * * mon,wed,fri");
  assert.equal(weekdays([]), "", "no day chosen is incomplete, not a default");
  for (const days of [["mon"], ["sat", "sun"], ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]) {
    assert.doesNotMatch(weekdays(days).split(" ")[4], /\d/, "never a numeric weekday");
  }
});

test("a blank new form starts unset; a stored expression is recognized", () => {
  assert.deepEqual(initialSchedule(""), { mode: "unset" }, "no default schedule, no raw cron");
  assert.equal(compileGuided({ mode: "unset" }), "");
  for (const expression of ["0 9 * * mon-fri", "*/15 * * * *", "0 9 * * 0-4", "0 9 30 2 *", " "]) {
    assert.deepEqual(initialSchedule(expression), recognizeSchedule(expression), JSON.stringify(expression));
  }
});

test("a stored expression opens guided only when it round-trips byte-for-byte", () => {
  const guided = {
    "*/15 * * * *": "minutes",
    "0 */1 * * *": "hours",
    "0 9 * * *": "daily",
    "30 18 * * *": "daily",
    "0 9 * * mon-fri": "weekdays",
    "0 9 * * sat,sun": "weekdays",
  };
  for (const [expression, mode] of Object.entries(guided)) {
    const recognized = recognizeSchedule(expression);
    assert.equal(recognized.mode, mode, expression);
    assert.equal(compileGuided(recognized), expression, `${expression} compiles back exactly`);
  }
  const custom = [
    "0 9 * * 0-4", // numeric weekdays keep APScheduler's Monday = 0: never reinterpreted
    "0 9 * * 0",
    "0 9 * * 6",
    "0 9 13 * fri",
    "*/7 * * * *",
    "0 */5 * * *",
    "00 9 * * *",
    "0 9 * * fri,mon",
    "0 9 * * mon,mon",
    " 0 9 * * *",
    "0  9 * * *",
    "0 9 30 2 *",
    "",
  ];
  for (const expression of custom) assert.deepEqual(recognizeSchedule(expression), { mode: "custom" }, expression);
});

const ready = (expression, valid, message = "This schedule never fires.") => ({
  status: "ready",
  expression,
  result: { valid, error: valid ? null : { code: "cron_never_fires", message } },
});

test("save gate: a new or changed expression needs the valid preview of exactly that expression", () => {
  const blocked = (stored, form, preview, blocker) => {
    const gate = scheduleSubmitGate(stored, form, preview);
    assert.equal(gate.canSubmit, false, `${form} with ${preview?.status}`);
    assert.match(gate.blocker, blocker);
  };
  blocked(null, "", undefined, /Choose how often the action runs/);
  blocked(null, "0 9 * * *", undefined, /Waiting for the next-run preview/);
  blocked(null, "0 9 * * *", { status: "loading", expression: "0 9 * * *" }, /Waiting/);
  // A reply for another expression is stale and never counts.
  blocked(null, "0 9 * * *", ready("0 8 * * *", true), /Waiting/);
  blocked(null, "0 9 * * *", { status: "failed", expression: "0 9 * * *", error: "boom" }, /Retry it before saving/);
  blocked(null, "0 9 30 2 *", ready("0 9 30 2 *", false), /never fires/);
  blocked("0 9 * * *", "0 10 * * *", ready("0 9 * * *", true), /Waiting/);

  assert.deepEqual(scheduleSubmitGate(null, "0 9 * * *", ready("0 9 * * *", true)), {
    canSubmit: true,
    sendCron: true,
    blocker: null,
    notice: null,
  });
});

test("save gate: an unchanged stored expression is omitted, even an invalid one, with a notice", () => {
  const legacy = "0 9 30 2 *";
  const loading = scheduleSubmitGate(legacy, legacy, { status: "loading", expression: legacy });
  assert.deepEqual([loading.canSubmit, loading.sendCron, loading.notice], [true, false, null]);
  const invalid = scheduleSubmitGate(legacy, legacy, ready(legacy, false));
  assert.deepEqual([invalid.canSubmit, invalid.sendCron], [true, false]);
  assert.match(invalid.notice, /unchanged and not valid: This schedule never fires\. Saving other fields keeps it/);
  const changedBack = scheduleSubmitGate("0 9 * * 0-4", "0 9 * * 0-4", ready("0 9 * * 0-4", true));
  assert.deepEqual([changedBack.canSubmit, changedBack.sendCron, changedBack.notice], [true, false, null]);
});

test("run times render from the server's local time, independent of the browser zone", () => {
  assert.equal(formatRunTime("2026-10-05T09:00:00+02:00"), "Mon 5 Oct 2026, 09:00 (UTC+02:00)");
  assert.equal(formatRunTime("2026-03-29T03:30:00+02:00"), "Sun 29 Mar 2026, 03:30 (UTC+02:00)");
  assert.equal(formatRunTime("2026-10-25T02:30:00+01:00"), "Sun 25 Oct 2026, 02:30 (UTC+01:00)");
  assert.equal(formatRunTime("2026-10-05T07:00:00Z"), "Mon 5 Oct 2026, 07:00 (UTC)");
  assert.equal(formatRunTime("not a time"), "not a time");
});
