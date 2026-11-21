// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/operationsModel.test.mjs
// Operations › Live: the presentation model turns the live payload into words,
// order, "x ago", costs and the actions a row offers. The server decides each run's state; the model never recomputes it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { agoText, costText, countTiles, itemStateLabel, jobText, liveAge, problemWords, runStateLabel } from "../../src/admin/components/operations/operationsWords.ts";
import { canStopJob, cardLine, itemLastSeen, runCostParts, runMainAction } from "../../src/admin/components/operations/operationsActions.ts";
import { itemWhereText, whereText } from "../../src/admin/components/operations/operationsWhere.ts";
import { readOperations } from "../../src/admin/components/operations/operationsRead.ts";
import { previewSentence, readStopHistory, readStopPreview, stopButtonLabel, stopCountText, stopResultText } from "../../src/admin/components/operations/operationsEmergencyStop.ts";
import { runStatusLabel } from "../../src/chat/workflowRun/workflowRunStatus.ts";

const GEN = "2026-11-13T07:50:20+00:00";
const ago = (s) => new Date(Date.parse(GEN) - s * 1000).toISOString();
const run = (over) => ({ id: "r", title: "Run", workspace: { id: "ws1", name: "Kitchen helper" }, work_item: null, state: "working", status: "running",
  current_node: { id: "work", title: "Work" }, last_event_at: ago(12), idle_seconds: 12, requested_by: { id: "u1", name: "Alex", is_me: true },
  where: null, cost_usd: 0.41, session_id: "s1", problems: [], items: [], ...over });

// This morning's case (07:50): Kitchen helper looping on core-domain, a spec run waiting 34 min silent 23 min.
const PAYLOAD = {
  generated_at: GEN,
  viewer: { id: "u1" },
  counts: { working: 1, needs_you: 1, silent: 1, looping: 1, problem: 0, cost_24h_usd: 9.84 },
  runs: [
    run({ id: "healthy", title: "Team delivery", state: "working" }),
    run({ id: "spec", title: "Spec writing", state: "needs_you", status: "waiting", idle_seconds: 34 * 60 }),
    run({ id: "silent", title: "Ticket delivery", state: "silent", idle_seconds: 23 * 60,
      problems: [{ key: "run:silent:silent", reason_code: "silent", severity: "attention", title: "No sign of life for 23 minutes" }] }),
    run({ id: "loop", title: "Team delivery", state: "looping", where: { kind: "device", device_id: "dev1", device_name: "", folder: "/Users/dev/kitchen-helper", model: "claude-sonnet-4-5", online: true },
      problems: [{ key: "run:loop:looping", reason_code: "looping", severity: "problem", title: "core-domain was started 38 times in 5 minutes" }],
      items: [
        { id: "core-domain", title: "core-domain", status: "running", iteration: 1, dispatches_5m: 38, session_id: "s2",
          job: { id: "dj_1", status: "rejected", status_reason: "workspace_preparation_workflow_run_not_bound", folder: "/Users/dev/kitchen-helper/.octryx-items/core-domain", device_id: "dev1", last_event_at: ago(2), cost_usd: 0 },
          problems: [{ key: "run:loop:looping", reason_code: "looping", severity: "problem", title: "x" }] },
        { id: "frontend-shell", title: "frontend-shell", status: "pending", iteration: 1, dispatches_5m: 0, session_id: "",
          job: { id: "dj_2", status: "waiting", status_reason: "device_busy", folder: "", device_id: "dev1", last_event_at: ago(3), cost_usd: 0 }, problems: [] },
      ] }),
  ],
  devices: [{ id: "dev1", name: "dev_4c6d", owner: { id: "u1", name: "Alex", is_me: true }, online: true, client_version: "0.3.2", outdated: false, jobs_running: 3, max_parallel_jobs: 4 }],
  seats: [{ user: { id: "u1", name: "Alex" }, five_hour_pct: 71 }],
};

test("runs come in the order of urgency: looping, problem, silent, needs you, working", () => {
  const live = readOperations(PAYLOAD);
  assert.deepEqual(live.runs.map((r) => r.id), ["loop", "silent", "spec", "healthy"]);
  assert.equal(live.counts.cost24hUsd, 9.84);
  assert.equal(live.viewerId, "u1");
  assert.equal(live.runs[0].items[0].dispatches5m, 38);
  assert.equal(readOperations({ runs: [run({ title: "Ticket delivery · OCX-19", workflow_title: "Ticket delivery" })] }).runs[0].title, "Ticket delivery", "the key is not repeated");
});

test("states are words with the contract's meaning; silence of a run waiting on a person is never 'silent'", () => {
  const [loop, silent, spec, healthy] = readOperations(PAYLOAD).runs;
  assert.deepEqual(runStateLabel(loop), { label: "Looping", tone: "problem", title: "core-domain was started 38 times in 5 minutes" });
  assert.deepEqual(runStateLabel(silent), { label: "Silent 23 min", tone: "attention", title: "No sign of life for 23 minutes" });
  assert.equal(runStateLabel({ ...silent, problems: [{ ...silent.problems[0], severity: "problem" }] }).tone, "problem", "≥ 45 min: the server says problem");
  assert.deepEqual(runStateLabel(spec), { label: "Needs you 34 min", tone: "attention", title: "" });
  assert.deepEqual(runStateLabel(healthy), { label: "Working", tone: "info", title: "" });
  // The state field wins: a long idle run the server calls "needs_you" is not turned into "silent" here.
  assert.equal(runStateLabel({ ...spec, idleSeconds: 3 * 3600 }).label, "Needs you 3 h");
});

test("reason codes never reach the UI", () => {
  assert.equal(problemWords({ reasonCode: "jobs_rejected" }), "Jobs refused");
  assert.equal(problemWords({ reasonCode: "job_stalled" }), "Stalled job");
  assert.equal(problemWords({ reasonCode: "silent" }, 23 * 60), "Silent 23 min");
  assert.equal(problemWords({ reasonCode: "something_new" }), "Problem");
  const [loop] = readOperations(PAYLOAD).runs;
  assert.equal(jobText(loop.items[0].job), "Refused: the working folder is not bound to this run");
  assert.equal(jobText(loop.items[1].job), "Waiting for the device");
  assert.deepEqual(itemStateLabel(loop.items[1]), { label: "Waiting", tone: "neutral", title: "" });
  assert.equal(itemStateLabel(loop.items[0]).label, "Looping");
});

test("times, costs and places", () => {
  assert.equal(agoText(2), "just now");
  assert.equal(agoText(12), "12 s ago");
  assert.equal(agoText(23 * 60), "23 min ago");
  assert.equal(agoText(null), "");
  assert.equal(liveAge(ago(12), GEN, 4), 16, "server clock plus the seconds since the answer");
  assert.equal(costText(0.41), "$0.41");
  assert.equal(costText(0), "$0.00");
  assert.equal(costText(0.001), "<$0.01");
  assert.equal(costText(null), "");
  const [loop] = readOperations(PAYLOAD).runs;
  assert.deepEqual(whereText(loop.where, readOperations(PAYLOAD).devices), { place: "dev_4c6d", detail: "kitchen-helper · Claude Sonnet 4.5" });
  assert.equal(whereText({ kind: "server", deviceId: "", deviceName: "", folder: "", model: "", online: null, label: "" }).place, "Server");
  assert.equal(itemWhereText(loop.items[0]), ".octryx-items/core-domain");
  assert.equal(cardLine(loop, readOperations(PAYLOAD).devices), "core-domain started 38× in 5 min · dev_4c6d");
});

test("the count bar colours only exceptions that are not zero", () => {
  const tiles = countTiles(readOperations(PAYLOAD).counts);
  assert.deepEqual(tiles.map((t) => [t.label, t.value, t.tone]), [
    ["Working", "1", "neutral"], ["Needs you", "1", "attention"], ["Silent", "1", "attention"],
    ["Looping", "1", "problem"], ["Problem", "0", "neutral"], ["API cost, last 24 h", "$9.84", "neutral"],
  ]);
});

test("the seat's API equivalent of the last 24 h is a tile of its own, never added to the API cost", () => {
  const counts = readOperations({ ...PAYLOAD, counts: { ...PAYLOAD.counts, seat_api_equivalent_24h_usd: 10.4 } }).counts;
  assert.deepEqual(countTiles(counts).slice(-2).map((t) => [t.label, t.value]), [
    ["API cost, last 24 h", "$9.84"], ["Seat: would cost via API (list price), last 24 h", "$10.40"],
  ]);
  assert.equal(countTiles({ ...counts, seatApiEquivalent24hUsd: 0 }).some((t) => t.key === "seat"), false);
});

test("actions: answer a waiting run; stop a device job only on my own device and only while it is active", () => {
  const live = readOperations(PAYLOAD);
  const [loop, , spec] = live.runs;
  assert.deepEqual(runMainAction(spec), { label: "Answer" });
  assert.deepEqual(runMainAction(loop), { label: "Open" });
  assert.equal(runMainAction({ ...loop, sessionId: "" }), null);
  const waitingJob = loop.items[1].job;
  assert.equal(canStopJob(waitingJob, { me: "u1", devices: live.devices }), true);
  const othersDevices = live.devices.map((d) => ({ ...d, owner: { ...d.owner, isMe: false } }));
  assert.equal(canStopJob(waitingJob, { me: "u2", devices: othersDevices }), false, "someone else's device");
  assert.equal(canStopJob(loop.items[0].job, { me: "u1", devices: live.devices }), false, "a refused job is not running");
});

test("is_me decides 'Needs you' and the owner's Stop; a missing place is no error", () => {
  const live = readOperations(PAYLOAD);
  const spec = live.runs.find((r) => r.id === "spec");
  const someoneElse = { ...spec, requestedBy: { id: "u2", name: "Anna", isMe: false }, responsible: null };
  assert.equal(runStateLabel(someoneElse).label, "Waits for Anna 34 min");
  assert.deepEqual(runMainAction(someoneElse), { label: "Open" });
  const job = live.runs[0].items[1].job;
  assert.equal(canStopJob(job, { me: "", devices: live.devices }), true, "owner.is_me without a viewer id");
  const notMine = live.devices.map((d) => ({ ...d, owner: { ...d.owner, isMe: false } }));
  assert.equal(canStopJob(job, { me: "", devices: notMine }), false);
  assert.deepEqual(whereText(null), { place: "", detail: "" });
  assert.equal(readOperations({ runs: [{ id: "x", where: null }] }).runs[0].where, null);
  assert.equal(itemLastSeen({ job: null, startedAt: "a", finishedAt: "b" }), "b");
});

// Emergency stop (contract §5).

test("emergency stop: who gets which button", () => {
  assert.equal(stopButtonLabel({ all: false, workspaceName: "Kitchen helper", isPlatformAdmin: false, viaAdminRoute: true }), "Stop everything in Kitchen helper");
  assert.equal(stopButtonLabel({ all: false, workspaceName: "Kitchen helper", isPlatformAdmin: false, viaAdminRoute: false }), null, "a member (Workspace route)");
  assert.equal(stopButtonLabel({ all: true, workspaceName: "", isPlatformAdmin: true, viaAdminRoute: true }), "Stop everything on the platform");
  assert.equal(stopButtonLabel({ all: true, workspaceName: "", isPlatformAdmin: false, viaAdminRoute: true }), null, "a Workspace admin never stops the platform");
});

test("emergency stop: preview, result and history in words", () => {
  const preview = readStopPreview({ workspace_id: "ws", runs: [{ id: "r1", title: "Team delivery", status: "running", current_node: "work", workspace: { id: "ws", name: "Kitchen helper" } }],
    device_jobs: [{ id: "dj1", folder: "/Users/dev/kitchen-helper/.octryx-items/core-domain", status: "running", workspace: { id: "ws", name: "Kitchen helper" } },
      { id: "dj2", folder: "/x/shell", status: "running", workspace: null }] });
  assert.deepEqual(preview.runs[0], { id: "r1", title: "Team delivery", workspace: "Kitchen helper", status: "running", node: "work" });
  assert.equal(preview.jobs[0].folder, ".octryx-items/core-domain");
  assert.equal(previewSentence(preview), "1 run pauses and 2 device jobs stop.");
  assert.match(previewSentence(readStopPreview({})), /^Nothing runs here right now/);
  assert.equal(stopResultText({ paused_runs: ["a", "b"], stopped_device_jobs: ["c"] }), "Stopped: 2 runs paused, 1 device job stopped.");
  const [row] = readStopHistory({ stops: [{ id: "k1", at: "2026-11-13T07:51:00Z", reason: "R1 loop", by: { id: "u1", name: "Alex" }, paused_runs: ["a"], stopped_device_jobs: [] }] });
  assert.deepEqual(row, { id: "k1", at: "2026-11-13T07:51:00Z", reason: "R1 loop", by: "Alex", runs: 1, jobs: 0 });
  assert.equal(stopCountText(row), "1 run · 0 jobs");
});

test("a run paused by the emergency stop reads so in Live and in the run view; Continue stays its own action", () => {
  const live = readOperations({ runs: [run({ id: "p", state: "problem", status: "paused", pause_reason: "emergency_stop" })] });
  assert.deepEqual(runStateLabel(live.runs[0]), { label: "Stopped by emergency stop", tone: "attention", title: "" });
  assert.equal(runStateLabel({ ...live.runs[0], pauseReason: "budget_limit" }).label, "Paused: the budget limit was reached");
  assert.equal(runStatusLabel({ status: "paused", pause_reason: "emergency_stop", waiting_kind: null, outcome: null }), "Stopped by emergency stop");
  assert.equal(runStatusLabel({ status: "paused", pause_reason: "budget_limit", waiting_kind: null, outcome: null }), "Paused · The run budget is used up");
});

test("a stopped run is its own state, after needs you, with a Stopped tile only while one exists", () => {
  const run = (id, state) => ({ id, title: id, state, status: state === "stopped" ? "paused" : "running", problems: [], items: [] });
  const live = readOperations({ counts: { working: 1, stopped: 1 }, runs: [run("w", "working"), run("s", "stopped"), run("n", "needs_you")] });
  assert.deepEqual(live.runs.map((r) => r.id), ["n", "s", "w"]);
  assert.equal(runStateLabel(live.runs[1]).label, "Stopped by emergency stop");
  assert.equal(problemWords({ reasonCode: "stopped" }), "Stopped by emergency stop");
  assert.deepEqual(countTiles(live.counts).find((t) => t.key === "stopped"), { key: "stopped", label: "Stopped", value: "1", tone: "attention" });
  assert.equal(countTiles(readOperations({ counts: { working: 1 } }).counts).some((t) => t.key === "stopped"), false);
});

test("a run paused by loop detection reads so in Live and in the run view", async () => {
  const { pauseTitle } = await import("../../src/chat/workflowRun/workflowRunStatus.ts");
  const live = readOperations({ runs: [{ id: "r", title: "Team delivery", state: "problem", status: "paused", pause_reason: "loop_detected", problems: [], items: [] }] });
  assert.deepEqual([runStateLabel(live.runs[0]).label, runStateLabel(live.runs[0]).tone], ["Loop detected · paused", "problem"]);
  assert.equal(pauseTitle("loop_detected"), "Loop detected · paused automatically");
  assert.equal(pauseTitle("runtime_failed", { code: "loop_detected" }), "Loop detected · paused automatically");
});

test("a paused run's problem reads its pause reason, never a bare 'Problem' or the code", () => {
  assert.equal(problemWords({ reasonCode: "action_failed" }), "Paused: an action failed");
  assert.equal(problemWords({ reasonCode: "something_new" }), "Problem");
});

test("a paused run without problem entries reads its pause reason", () => {
  const live = readOperations({ runs: [{ id: "r", title: "Feature delivery", state: "problem", status: "paused", pause_reason: "watch_timeout", problems: [], items: [] }] });
  assert.equal(runStateLabel(live.runs[0]).label, "Paused: waiting for merge took too long");
});

test("a run's API cost and its seat's API equivalent stay two parts", () => {
  const live = readOperations({ ...PAYLOAD, runs: [{ ...PAYLOAD.runs[0], cost_usd: 0, seat_api_equivalent_usd: 4.2, seat_unpriced_calls: 2 }] });
  const [run] = live.runs;
  assert.equal(run.costUsd, 0);
  assert.deepEqual(run.seat, { equivalentUsd: 4.2, unpricedCalls: 2 });
  assert.deepEqual(runCostParts(run), ["API $0.00", "Seat $4.20 (list price)"]);
  assert.deepEqual(runCostParts({ costUsd: 0.41, seat: { equivalentUsd: 0, unpricedCalls: 0 } }), ["API $0.41"]);
  assert.deepEqual(runCostParts({ costUsd: null, seat: { equivalentUsd: 0, unpricedCalls: 5 } }), ["Seat: 5 calls, no list price"]);
});
