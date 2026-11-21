import assert from "node:assert/strict";
import { test } from "node:test";
import {
  codingQueueEmptyState,
  codingSessionsNote,
  isCodingQueue,
  sessionInQueue,
} from "../../src/chat/coding/codingQueuePresenter.ts";
import {
  START_DIALOG_COPY,
  appendRepository,
  filterStartCandidates,
  startListMessage,
} from "../../src/chat/coding/codingStartCandidates.ts";

const context = { queueCount: 0, workItemCount: 12, search: "" };

test("every queue explains itself with its own empty state and next step", () => {
  const states = ["sessions", "review", "blocked", "completed"].map((queue) => codingQueueEmptyState(queue, context));
  assert.equal(new Set(states.map((state) => state.title)).size, 4);
  assert.equal(new Set(states.map((state) => state.body)).size, 4);
  for (const state of states) {
    assert.doesNotMatch(`${state.title} ${state.body}`, /\bOE\b/);
    assert.ok(state.actions.length >= 1);
  }
  const [cockpit, review, blocked, completed] = states;
  assert.deepEqual(cockpit.actions, [{ kind: "startSession", label: "Start coding session" }]);
  assert.match(cockpit.body, /12 work items are available/);
  assert.match(review.body, /Work → Plans · Waiting for review/);
  assert.ok(review.actions.some((action) => action.kind === "link" && action.href === "/chat?area=work"));
  assert.match(blocked.body, /resolve it on the work item in Work or by creating a new change plan/);
  assert.match(completed.body, /history/);
});

test("cockpit without work items points to Work instead of starting a session", () => {
  const state = codingQueueEmptyState("sessions", { ...context, workItemCount: 0 });
  assert.match(state.body, /Work → Intake/);
  assert.deepEqual(state.actions, [{ kind: "link", label: "Open Work", href: "/chat?area=work" }]);
});

test("a search that hides queue entries offers to clear the search", () => {
  const state = codingQueueEmptyState("blocked", { queueCount: 3, workItemCount: 12, search: " pay " });
  assert.equal(state.title, 'No coding session in this queue matches "pay".');
  assert.deepEqual(state.actions, [{ kind: "clearSearch", label: "Clear search" }]);
});

test("No count cards; one line says only what the filter tabs do not (waiting for a plan), else nothing", () => {
  assert.equal(codingSessionsNote([]), null);
  assert.equal(codingSessionsNote([{ state: "implementing", phase: "implementing" }, { state: "completed", phase: "completed" }]), null,
    "counts per state are the tabs' counts");
  assert.equal(codingSessionsNote([
    { state: "implementing", phase: "implementing" },
    { state: "draft", phase: "ready_to_plan" },
  ]), "1 waiting for a plan");
});

test("queue membership follows the session state", () => {
  assert.equal(isCodingQueue("review"), true);
  assert.equal(isCodingQueue("policies"), false);
  assert.equal(sessionInQueue({ state: "pr_open" }, "review"), true);
  assert.equal(sessionInQueue({ state: "changes_requested" }, "blocked"), true);
  assert.equal(sessionInQueue({ state: "completed" }, "completed"), true);
  assert.equal(sessionInQueue({ state: "completed" }, "review"), false);
  assert.equal(sessionInQueue({ state: "draft" }, "sessions"), true);
});

test("start dialog says the session starts with a change plan and explains an empty work list", () => {
  assert.equal(START_DIALOG_COPY.title, "Start coding session");
  assert.equal(START_DIALOG_COPY.submit, "Create change plan and start");
  assert.match(START_DIALOG_COPY.intro, /starts with a change plan/);
  assert.equal(startListMessage(0, 0), "No work items available — import them in Work → Intake.");
  assert.equal(startListMessage(5, 0), "No work items match the search.");
  assert.equal(startListMessage(5, 5), null);
  const items = [
    { source_key: "RIVER-1", title: "Pay out", labels: ["payments"] },
    { source_key: "RIVER-2", title: "Audit log", labels: [] },
  ];
  assert.deepEqual(filterStartCandidates(items, "payments").map((item) => item.source_key), ["RIVER-1"]);
  assert.equal(appendRepository("", "core"), "core");
  assert.equal(appendRepository("core", "core"), "core");
  assert.equal(appendRepository("core\n", "web"), "core\nweb");
});
