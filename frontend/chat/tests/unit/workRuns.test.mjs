// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workRuns.test.mjs
//
// Work › Runs (UX audit Alex OK on the mock): runs waiting for a person on top, every run with its step
// ("Build · 2 of 4"), result (the pull request) and model cost.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  runWorkflowTitle,
  costText,
  resultText,
  runName,
  statusWord,
  splitRuns,
  stepText,
  runSeat,
  totalCost,
  totalSeat,
  waitingText,
  workflowName,
  workRunsPath,
} from "../../src/chat/work/workRunsModel.ts";

const base = { id: "r", title: "OCX-53 · Retry", workflow_key: "epic-delivery", workflow_kind: "phased",
  waiting_kind: null, pause_reason: null, outcome: null, updated_at: null };

test("the list asks for the work view of the workspace", () => {
  assert.equal(workRunsPath("p1"), "/api/v1/workflow-runs?view=work&project_id=p1");
  assert.equal(workRunsPath(null), "/api/v1/workflow-runs?view=work");
});

test("step, result and cost read like the mock", () => {
  const building = { ...base, status: "running", step: { title: "Build", kind: "phase", index: 2, total: 4 }, cost: 0.71 };
  assert.equal(stepText(building), "Build · 2 of 4");
  assert.equal(resultText(building), "–");
  assert.equal(costText(building.cost), "$0.71");
  const shipped = { ...base, status: "completed", pull_request: { id: 1440, url: "https://x/pr/1440" }, cost: 2.12 };
  assert.equal(stepText(shipped), "");
  assert.equal(statusWord(shipped), "Shipped");
  assert.equal(resultText(shipped), "PR #1440");
  // Bitbucket Server: the pull request has an id but no link; it still counts as shipped.
  const noLink = { ...base, status: "completed", pull_request: { id: 41, url: "", state: "open" } };
  assert.equal(statusWord(noLink), "Shipped");
  assert.equal(resultText(noLink), "PR #41");
  const stopped = { ...base, status: "completed", outcome: "stopped", stop_reason: "x ".repeat(60),
    step: { title: "Implement", kind: "phase", index: 2, total: 2 } };
  assert.equal(statusWord(stopped), "Stopped");
  assert.equal(stepText({ ...stopped, status: "stopped" }), "at Implement");
  assert.ok(resultText(stopped).endsWith("…") && resultText(stopped).length <= 70);
  assert.equal(resultText({ ...base, status: "completed", outcome: "done" }), "–");
  assert.equal(runName({ ...base, work_item: { key: "OCX-37", title: "benchmark run T3" } }), "OCX-37 · benchmark run T3");
  assert.equal(runName(base), "OCX-53 · Retry");
  assert.equal(costText(0), "–");
  assert.equal(workflowName("epic-delivery"), "Epic delivery");
  assert.equal(totalCost([building, shipped, { ...base, status: "failed" }]).toFixed(2), "2.83");
});

test("the seat's API equivalent is summed apart from the API cost, never into it", () => {
  const seat = { ...base, status: "completed", cost: 0, seat_api_equivalent: 9.87, seat_unpriced_calls: 4 };
  const api = { ...base, status: "completed", cost: 1.25 };
  const both = { ...base, status: "completed", cost: 0.5, seat_api_equivalent: 0.13 };
  assert.equal(totalCost([seat, api, both]), 1.75);
  assert.deepEqual(totalSeat([seat, api, both]), { equivalentUsd: 10, unpricedCalls: 4 });
  assert.deepEqual(runSeat(api), { equivalentUsd: 0, unpricedCalls: 0 }, "an API run has no seat figure");
  assert.deepEqual(runSeat({ ...base, seat_api_equivalent: "3", seat_unpriced_calls: -1 }), { equivalentUsd: 0, unpricedCalls: 0 });
});

test("waiting and paused runs come first and say why", () => {
  const deciding = { ...base, id: "a", status: "waiting", waiting_kind: "awaiting_confirmation",
    step: { title: "Decide", kind: "user_confirmation", index: null, total: 3 } };
  const paused = { ...base, id: "b", status: "paused", pause_reason: "runtime_failed",
    pause: { code: "agent_loop", loop_kind: "noop" } };
  const { waiting, others } = splitRuns([{ ...base, id: "c", status: "running" }, deciding, paused]);
  assert.deepEqual(waiting.map((run) => run.id), ["a", "b"]);
  assert.deepEqual(others.map((run) => run.id), ["c"]);
  assert.match(waitingText(deciding), /^Decide · /);
  assert.match(waitingText(paused), /^Paused: /);
});

test("a run names its workflow by the workflow's title; a run without a title by its key", () => {
  assert.equal(runWorkflowTitle({ workflow_key: "pr-review-bot", workflow_title: "PR review bot" }), "PR review bot");
  assert.equal(runWorkflowTitle({ workflow_key: "bug-fix-reproduction", workflow_title: null }), "Bug fix reproduction");
});
