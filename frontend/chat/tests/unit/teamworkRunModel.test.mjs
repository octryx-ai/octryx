// Teamwork (WP-D, run view model): context.work → the rows a Parallel work box shows while the run is live.
import assert from "node:assert/strict";
import { test } from "node:test";

import { workItemRows, workPlanned, workSummary } from "../../src/chat/workflowRun/teamworkModel.ts";

const WORK = {
  node_id: "build", plan_version: 2, executor: "device", route: null,
  items: {
    "csv-escaping": { id: "csv-escaping", title: "CSV escaping", role: "backend", model: "claude-haiku-5-5", depends_on: [],
      status: "conflict", iteration: 1, conflicts: ["server/export/csv.ts"] },
    "export-ui": { id: "export-ui", title: "Export button and dialog", role: "frontend", model: "claude-haiku-5-5",
      depends_on: ["api-export"], status: "running", iteration: 1 },
    "api-export": { id: "api-export", title: "API: export endpoint", role: "backend", model: "claude-haiku-5-5",
      depends_on: [], status: "merged", iteration: 1 },
    "export-test": { id: "export-test", title: "System test: export file", role: "test", model: null,
      depends_on: ["api-export"], status: "running", iteration: 2, reason: "reopened by plan v2" },
  },
};

test("before the coordinator's plan the box is split at run time", () => {
  assert.equal(workPlanned(undefined), false);
  assert.equal(workPlanned({ items: {} }), false);
  assert.equal(workSummary(null), "split at run time");
  assert.deepEqual(workItemRows({}), []);
});

test("items come in the order they can run, with role, model, status, round and what they wait for", () => {
  const rows = workItemRows(WORK);
  assert.deepEqual(rows.map((row) => row.id), ["api-export", "csv-escaping", "export-test", "export-ui"]);
  const byId = Object.fromEntries(rows.map((row) => [row.id, row]));
  assert.deepEqual([byId["api-export"].label, byId["api-export"].tone, byId["api-export"].model], ["Merged", "neutral", "Claude Haiku 5.5"]);
  assert.equal(byId["export-ui"].after, "after API: export endpoint");
  assert.deepEqual(byId["export-ui"].dependsOn, ["api-export"]);
  assert.equal(byId["export-test"].round, "round 2");
  assert.equal(byId["export-test"].model, "");
  assert.deepEqual([byId["csv-escaping"].label, byId["csv-escaping"].tone, byId["csv-escaping"].detail],
    ["Merge conflict", "problem", "Conflicts in server/export/csv.ts"]);
});

test("the header line counts what matters and says when the run goes back to the plan", () => {
  assert.equal(workSummary(WORK), "4 items · 2 running · 1 merged · 1 merge conflict");
  assert.equal(workSummary({ ...WORK, route: "replan" }), "4 items · 2 running · 1 merged · 1 merge conflict · back to the plan");
});

test("unknown statuses read as waiting and a dependency cycle never hangs", () => {
  const rows = workItemRows({ items: {
    a: { id: "a", depends_on: ["b"], status: "weird" }, b: { id: "b", depends_on: ["a"] } } });
  assert.deepEqual(rows.map((row) => [row.id, row.status]), [["b", "pending"], ["a", "pending"]]);
});

test("the run payload's list in plan order reads the same as the map, with the item's chat and branch", () => {
  const list = Object.values(WORK.items).map((item) => item.id === "export-ui"
    ? { ...item, session_id: "s-42", branch: "story/ocx-24-export-ui" } : item);
  const rows = workItemRows({ ...WORK, items: list });
  assert.deepEqual(rows.map((row) => row.id), ["api-export", "csv-escaping", "export-test", "export-ui"]);
  assert.deepEqual([rows[3].sessionId, rows[3].branch, rows[3].tone], ["s-42", "story/ocx-24-export-ui", "info"]);
  assert.equal(workSummary({ ...WORK, items: list }), "4 items · 2 running · 1 merged · 1 merge conflict");
});

test("a Parallel work box is a step of the run like a phase", async () => {
  const { runSteps } = await import("../../src/chat/workflowRun/runCardModel.ts");
  const steps = runSteps({ status: "running", phase_position: { index: null, total: 1 },
    nodes: [{ id: "plan", kind: "phase", title: "Plan the work" }, { id: "ready", kind: "decision", title: "Ready?" },
      { id: "work", kind: "parallel_work", title: "Build the story" }, { id: "pr", kind: "action", title: "PR" }],
    current_node: { id: "work", kind: "parallel_work", title: "Build the story" } });
  assert.deepEqual(steps.map((step) => [step.id, step.state]), [["plan", "done"], ["work", "active"]]);
});

test("on a Parallel work box the bar says which phase it is, as on an agent phase", async () => {
  const { runPhaseShort } = await import("../../src/chat/workflowRun/runBarModel.ts");
  assert.equal(runPhaseShort({ status: "running", phase_position: { index: 2, total: 3 },
    current_node: { id: "work", kind: "parallel_work", title: "Team: backend · frontend · test" } }), "Phase 2/3");
});

test("a card with many dependencies names the first and counts the rest; raw reason tokens read in words (CHEF-2 run)", () => {
  const work = { items: [
    { id: "a", title: "API" }, { id: "b", title: "UI" }, { id: "c", title: "Profile" }, { id: "d", title: "Matching" },
    { id: "t", title: "Tests", depends_on: ["a", "b", "c", "d"], status: "pending", reason: "branching" },
    { id: "u", title: "Docs", depends_on: ["a"], status: "pending", reason: "some_new_token" },
  ] };
  const byId = Object.fromEntries(workItemRows(work).map((row) => [row.id, row]));
  assert.equal(byId.t.after, "after API +3");
  assert.equal(byId.t.afterAll, "after API, UI, Profile, Matching");
  assert.deepEqual([byId.t.afterFirst, byId.t.afterMore], ["API", 3]);
  assert.equal(byId.t.detail, "Preparing branch");
  assert.equal(byId.u.after, "after API");
  assert.equal(byId.u.detail, "", "an unknown lowercase token is not shown raw");
});

test("a refusal code inside a failure reason reads in words, a code name in the reason stays", () => {
  const work = { items: [
    { id: "s", title: "Web shell", status: "failed",
      reason: "its start was refused 3 times in a row (last: registration_refused); the item never ran" },
    { id: "v", title: "View", status: "failed", reason: "order_history_view returns 21 rows" },
  ] };
  const byId = Object.fromEntries(workItemRows(work).map((row) => [row.id, row]));
  assert.equal(byId.s.detail, "its start was refused 3 times in a row (last: the device refused the job); the item never ran");
  assert.equal(byId.v.detail, "order_history_view returns 21 rows");
});
