// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionModel.test.mjs
//
// Octryx companion, stage 1: reading GET /api/v1/attention tolerantly, the octopus' face and eight arm
// nodes ("+N" on the eighth), the notify rules, the request an action sends (free text into body[input.field]),
// quiet hours (default 19:00–08:00 Europe/Zurich, PUT keeps the channel switches).
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_QUIET_HOURS } from "../../src/chat/companion/companionTypes.ts";
import { armNodes, armsMoving, buildActionRequest, companionLabel, countdownText, faceState, itemsToNotify, notifies, quietHoursBody, readQuietHours, secondsLeft, validQuietHours } from "../../src/chat/companion/companionModel.ts";
import { readAttention, readAttentionItem } from "../../src/chat/companion/companionRead.ts";

const json = (value) => JSON.parse(JSON.stringify(value));
const QUESTION = {
  key: "question:q1", kind: "question", id: "q1", title: "Which branch should I use?", subtitle: "Agent of Anna", created_at: "2026-11-06T09:00:00Z",
  severity: "action", workspace: { id: "ws-1", name: "BRD team" }, work_item: { id: "wi-6", key: "BRD-6", title: "Onboarding" },
  text: "main or release/2.4?", link: { href: "/chat?area=work&work_item_id=wi-6", label: "Open work item" },
  actions: [
    { key: "main", label: "main", tone: "primary", request: { method: "POST", path: "/api/v1/clarifications/q1/answer", body: { answer: "main" } } },
    { key: "text", label: "Send answer", tone: "neutral", input: { kind: "text", label: "Your answer", placeholder: "Type…", required: true, field: "answer" },
      request: { method: "POST", path: "/api/v1/clarifications/q1/answer", body: { source: "companion" } } },
  ],
};
const DONE = { kind: "done", id: "r1", title: "BRD-6 is done", severity: "info", actions: [
  { key: "dismiss", label: "Dismiss", tone: "neutral", request: { method: "POST", path: "/api/v1/attention/done:r1/dismiss", body: {} } }] };
const run = (id, state = "working") => ({ id, state, current_node: "implement", runtime_target: { kind: "server", label: "Server", profile: "p", reason: "" },
  work_item: { id: `wi-${id}`, key: `BRD-${id}`, title: "Task" }, session_id: `s-${id}`, updated_at: "2026-11-06T09:00:00Z" });
const payload = (extra = {}) => ({ items: [], running: [], count: 0, cursor: null, quiet: { active: false, until: null }, ...extra });

test("the attention payload is read tolerantly; unknown kinds, foreign paths and links are dropped", () => {
  assert.equal(readAttention({}), null);
  assert.equal(readAttention(null), null);
  const read = readAttention(payload({ items: [QUESTION, { kind: "shell", id: "x" }, { kind: "done" }, DONE], running: [run("1"), {}], count: 1 }));
  assert.deepEqual(read.items.map((item) => item.key), ["question:q1", "done:r1"]);
  assert.equal(read.running.length, 1);
  assert.equal(read.running[0].label, "BRD-1 Task");
  const target = readAttention(payload({ running: [{ ...run("9"), runtime_target: { kind: "device", label: "Alex's Mac", device_name: "MacBook", folder: "~/oe",
    online: false, resolved_from: "work_item" } }] })).running[0].target;
  assert.deepEqual(json(target), { kind: "device", label: "Alex's Mac", deviceName: "MacBook", folder: "~/oe", profile: "", online: false, resolvedFrom: "work_item", reason: "" });
  assert.equal(read.items[0].workItem.key, "BRD-6");
  const foreign = readAttentionItem({ ...QUESTION, link: { href: "https://evil.example/x" }, actions: [
    { key: "a", label: "Go", request: { method: "POST", path: "https://evil.example/api/v1/x" } },
    { key: "b", label: "Up", request: { method: "POST", path: "/api/v1/../admin" } },
    { key: "c", label: "Get", request: { method: "GET", path: "/api/v1/x" } },
  ] });
  assert.equal(foreign.link, null, "only same-origin links");
  assert.deepEqual(foreign.actions, [], "only same-origin /api/ requests with a write method");
});

test("face: worry on a problem, open when something needs you, sleep in quiet hours or with nothing on, else calm", () => {
  assert.equal(faceState(null), "sleep");
  assert.equal(faceState(readAttention(payload())), "sleep");
  assert.equal(faceState(readAttention(payload({ running: [run("1")] }))), "calm");
  assert.equal(faceState(readAttention(payload({ items: [DONE] }))), "calm");
  assert.equal(faceState(readAttention(payload({ items: [QUESTION], running: [run("1")] }))), "open");
  assert.equal(faceState(readAttention(payload({ running: [run("1", "needs_you")] }))), "open");
  assert.equal(faceState(readAttention(payload({ items: [QUESTION, { kind: "problem", id: "p1", title: "CI failed" }] }))), "worry");
  assert.equal(faceState(readAttention(payload({ running: [run("1"), run("2", "problem")] }))), "worry");
  assert.equal(faceState(readAttention(payload({ running: [run("1")], quiet: { active: true, until: "2026-11-07T07:00:00Z" } }))), "sleep");
});

test("eight arm nodes: one per run, idle when free, off when not connected, +N on the eighth", () => {
  const states = ["working", "needs_you", "done", "problem"];
  const four = armNodes(readAttention(payload({ running: states.map((state, index) => run(String(index), state)) })).running);
  assert.deepEqual(four.map((node) => node.state), ["run", "wait", "done", "fail", "idle", "idle", "idle", "idle"]);
  assert.equal(armsMoving(four), true);
  assert.equal(armsMoving(armNodes([])), false, "nothing works, nothing moves");
  assert.deepEqual(armNodes([], false).map((node) => node.state), Array(8).fill("off"));
  const eight = armNodes(readAttention(payload({ running: Array.from({ length: 8 }, (_, index) => run(String(index))) })).running);
  assert.equal(eight[7].more, 0, "exactly eight runs fit");
  const eleven = armNodes(readAttention(payload({ running: Array.from({ length: 11 }, (_, index) => run(String(index))) })).running);
  assert.equal(eleven.length, 8);
  assert.equal(eleven[7].more, 4, "the eighth node stands for the four runs that have no arm");
  assert.equal(eleven[7].label, "4 more runs");
});

test("notify rules: questions, gates, approvals, done and problems notify; budget from 80 %, allowance from 95 %", () => {
  for (const kind of ["question", "gate", "device_approval", "done", "problem", "handover"]) {
    assert.equal(notifies(readAttentionItem({ kind, id: "1" })), true, kind);
  }
  assert.equal(notifies(readAttentionItem({ kind: "budget", id: "b", percent: 79 })), false);
  assert.equal(notifies(readAttentionItem({ kind: "budget", id: "b", percent: 80 })), true);
  assert.equal(notifies(readAttentionItem({ kind: "allowance", id: "a", percent: 94 })), false);
  assert.equal(notifies(readAttentionItem({ kind: "allowance", id: "a", percent: 95 })), true);
  // Phase changes, finished turns and green tests are not attention kinds: they are never items, so never notify.
  for (const kind of ["phase_changed", "turn_finished", "tests_green"]) assert.equal(readAttentionItem({ kind, id: "1" }), null, kind);
  const first = readAttention(payload({ items: [QUESTION] }));
  assert.deepEqual(itemsToNotify(null, first), [], "the first load is the baseline");
  const next = readAttention(payload({ items: [QUESTION, DONE] }));
  assert.deepEqual(itemsToNotify(new Set(["question:q1"]), next).map((item) => item.key), ["done:r1"]);
  assert.deepEqual(itemsToNotify(new Set(), { ...next, quiet: { active: true, until: null } }), [], "quiet hours notify nothing");
});

test("action requests: an option sends its own body, free text goes into body[input.field], required text is checked", () => {
  const item = readAttentionItem(QUESTION);
  assert.deepEqual(json(buildActionRequest(item.actions[0])), { method: "POST", path: "/api/v1/clarifications/q1/answer", body: { answer: "main" } });
  assert.deepEqual(json(buildActionRequest(item.actions[1], "  release/2.4 ")),
    { method: "POST", path: "/api/v1/clarifications/q1/answer", body: { source: "companion", answer: "release/2.4" } });
  assert.deepEqual(buildActionRequest(item.actions[1], "  "), { error: "Your answer is required." });
  assert.deepEqual(item.actions[1].request.body, { source: "companion" }, "the item's own request stays unchanged");
  // An answer option is its own action without input; its body already carries the answer.
  assert.equal(item.actions[0].input, null);
  const synthesized = readAttentionItem({ kind: "done", id: "r2", key: "done:r2", title: "Done" }).actions;
  assert.deepEqual(json(synthesized.map((action) => action.request)), [{ method: "POST", path: "/api/v1/attention/dismiss", body: { key: "done:r2" } }],
    "a done item without its own dismiss gets POST /api/v1/attention/dismiss {key}");
  const dismiss = readAttentionItem(DONE).actions[0];
  assert.deepEqual(json(buildActionRequest(dismiss)), { method: "POST", path: "/api/v1/attention/done:r1/dismiss", body: {} });
});

test("label, countdown and quiet hours", () => {
  assert.equal(companionLabel(readAttention(payload({ items: [QUESTION], running: [run("1"), run("2"), run("3")] }))), "Octryx: 1 needs you, 3 working");
  assert.equal(companionLabel(readAttention(payload())), "Octryx: nothing needs you");
  assert.equal(companionLabel(null), "Octryx: not connected");
  const now = Date.parse("2026-11-06T09:00:00Z");
  assert.equal(secondsLeft("2026-11-06T09:02:05Z", now), 125);
  assert.equal(countdownText(125), "2:05 left");
  assert.equal(countdownText(secondsLeft("2026-11-06T08:00:00Z", now)), "Expired");
  assert.equal(secondsLeft(null, now), null);
  assert.deepEqual(DEFAULT_QUIET_HOURS, { enabled: true, start: "19:00", end: "08:00", timezone: "Europe/Zurich" });
  assert.deepEqual(readQuietHours({ in_app_enabled: true }), { quiet: DEFAULT_QUIET_HOURS, stored: false });
  assert.deepEqual(readQuietHours({ quiet_hours: { enabled: false, start: "20:00", end: "07:30", timezone: "Europe/Berlin" } }),
    { quiet: { enabled: false, start: "20:00", end: "07:30", timezone: "Europe/Berlin" }, stored: true });
  assert.equal(readQuietHours({ quiet_hours: { start: "25:00", end: "07:00" } }).stored, false);
  assert.equal(validQuietHours({ ...DEFAULT_QUIET_HOURS, end: "19:00" }), false);
  assert.deepEqual(quietHoursBody({ user_id: "u", in_app_enabled: true, email_enabled: true, slack_enabled: false }, DEFAULT_QUIET_HOURS),
    { in_app_enabled: true, email_enabled: true, slack_enabled: false, quiet_hours: DEFAULT_QUIET_HOURS }, "the PUT keeps the channel switches");
});

test("an activity problem about a run opens that run; one about a device job does not", () => {
  const run = readAttentionItem({
    kind: "problem", id: "5c9b537a", key: "activity:run:5c9b537a:looping", severity: "warning", code: "looping",
    title: "core-domain started 38× in 5 min", problem: { object: { type: "workflow_run", id: "5c9b537a" } },
  });
  assert.equal(run.runId, "5c9b537a");
  assert.equal(run.key, "activity:run:5c9b537a:looping");
  const job = readAttentionItem({
    kind: "problem", id: "dj_1", key: "activity:device:dj_1:job_stalled", title: "Stalled",
    problem: { object: { type: "device_job", id: "dj_1" } }, link: { href: "/chat?session_id=s1" },
  });
  assert.equal(job.runId, null);
  assert.equal(job.link.href, "/chat?session_id=s1");
});
