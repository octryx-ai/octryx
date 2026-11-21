// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/mobileRuns.test.mjs
//
// Runs on the phone: the list rows read Work › Runs' payload (a run that waits is "needs you" and the
// only coloured state besides a failure), the filters count what they show, and the run view's steps follow the
// workflow's main path: branches (recovery boxes, the other ends) never read as steps still to come.
import assert from "node:assert/strict";
import { test } from "node:test";
import { defaultRunFilter, readRunRows, runCounts, runMatches, runTimeline } from "../../src/mobile/mobileRuns.ts";

const LIST = {
  runs: [
    { id: "r1", title: "Epic delivery · OCX-23", workflow_key: "epic-delivery", status: "waiting", waiting_kind: "awaiting_confirmation",
      work_item: { key: "OCX-23", title: "Order history" }, project_id: "shop", step: { title: "Product owner: ship it or answer", index: null, total: 2 } },
    { id: "r2", title: "Epic delivery · OCX-22", workflow_key: "epic-delivery", status: "running",
      work_item: { key: "OCX-22", title: "Login with SSO" }, project_id: "shop", step: { title: "Implement", index: 2, total: 2 } },
    { id: "r3", title: "Nightly check", workflow_key: "pr-review-bot", status: "completed", outcome: "done", project_id: "shop", step: { title: "Done" } },
    { title: "no id" },
  ],
};

test("list rows name the Work item, the workflow and the step; only waiting and failed runs are coloured", () => {
  const [waiting, running, done] = readRunRows(LIST);
  assert.equal(readRunRows(LIST).length, 3);
  assert.equal(waiting.subject, "OCX-23 · Order history");
  assert.equal(waiting.label, "Waiting for your confirmation");
  assert.equal(waiting.tone, "attention");
  assert.equal(waiting.needsYou, true);
  assert.equal(running.step, "Implement · phase 2 of 2");
  assert.equal(running.tone, "info");
  assert.equal(done.subject, "Nightly check");
  assert.equal(done.workflow, "PR review bot");
  assert.equal(done.step, "");
  assert.equal(done.tone, "neutral");
  assert.deepEqual(readRunRows(null), []);
});

test("the filters count what they show and the phone opens on what waits for the person", () => {
  const rows = readRunRows(LIST);
  assert.deepEqual(runCounts(rows), { needs: 1, active: 2, finished: 1, all: 3 });
  assert.equal(defaultRunFilter(rows), "needs");
  assert.equal(defaultRunFilter(rows.filter((row) => !runMatches(row, "needs"))), "active");
  assert.equal(defaultRunFilter([]), "all");
});

const NODES = [
  { id: "start", kind: "start", title: "Start" },
  { id: "implement", kind: "phase", title: "Implement" },
  { id: "review", kind: "review", title: "Review" },
  { id: "decide", kind: "user_confirmation", title: "Ship it?" },
  { id: "stopped", kind: "outcome", title: "Stopped" },
  { id: "pr", kind: "platform_action", title: "Pull request" },
  { id: "done", kind: "outcome", title: "Done" },
  { id: "failed", kind: "pause", title: "A step failed" },
];

test("the steps follow the main path: before the current one done, it waits, the rest comes", () => {
  const steps = runTimeline({ nodes: NODES, current_node: NODES[3], status: "waiting" });
  assert.deepEqual(steps.map((step) => `${step.id}:${step.state}`), ["implement:done", "review:done", "decide:waiting", "pr:next"]);
});

test("a finished run shows the end it reached; a recovery box claims no step done", () => {
  const done = runTimeline({ nodes: NODES, current_node: NODES[6], status: "completed" });
  assert.deepEqual(done.map((step) => step.id), ["implement", "review", "decide", "pr", "done"]);
  assert.ok(done.every((step) => step.state === "done"));
  const paused = runTimeline({ nodes: NODES, current_node: NODES[7], status: "paused" });
  assert.deepEqual(paused.map((step) => `${step.id}:${step.state}`),
    ["implement:next", "review:next", "decide:next", "pr:next", "failed:waiting"]);
});
