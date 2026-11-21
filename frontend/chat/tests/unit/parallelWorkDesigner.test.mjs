// Teamwork (WP-D, designer half): a "Parallel work" box runs the coordinator's plan as items side by side at run time.
// It has the closed exits done and replan; a fork drawn by hand stays refused, and the message points to Parallel work.
import assert from "node:assert/strict";
import { test } from "node:test";

import { exitValues } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/exitValues.ts";
import { kindName } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/labels.ts";
import { edgeIssues, PARALLEL_HINT } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/patch.ts";
import { boxSubtitle, familyLabel, nodeFamily } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphWords.ts";
import { buildPhasedGraph, drawnArrows } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphBuild.ts";
import { layoutPhasedGraph } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphLayout.ts";

const CATALOG = { agents: [], tools: [], checkTypes: [], outcomes: [], platformActions: [] };
const ROLES = { backend: { agent: "engineer", model: "claude-haiku-5-5" }, frontend: { agent: "engineer" }, test: { agent: "engineer" } };

test("Parallel work is its own box family with the exits done and replan", () => {
  assert.equal(nodeFamily("parallel_work"), "parallel");
  assert.equal(familyLabel("parallel"), "Parallel work");
  assert.equal(kindName("parallel_work"), "Parallel work");
  assert.deepEqual(exitValues({ id: "build", type: "parallel_work", label: "Build", config: {} }, CATALOG), ["done", "replan"]);
  assert.equal(boxSubtitle({ id: "build", kind: "parallel_work", title: "Build", config: { roles: ROLES } }),
    "backend · frontend · test — split at run time");
  assert.equal(boxSubtitle({ id: "build", kind: "parallel_work", title: "Build", config: {} }), "no roles set — split at run time");
});

test("a fork drawn by hand is refused and points to Parallel work", () => {
  const nodes = [
    { id: "plan", type: "phase", label: "Plan the work", config: {} },
    { id: "backend", type: "phase", label: "Backend", config: {} },
    { id: "frontend", type: "phase", label: "Frontend", config: {} },
  ];
  const edges = [
    { id: "a", source: "plan", target: "backend", kind: "next", when: null, max_iterations: null },
    { id: "b", source: "plan", target: "frontend", kind: "next", when: null, max_iterations: null },
  ];
  const messages = edgeIssues(edges[1], edges, nodes, CATALOG).map((issue) => issue.message);
  assert.ok(messages.some((message) => message.includes("remove the extra arrow") && message.endsWith(PARALLEL_HINT)), messages.join(" | "));
});

test("the replan way back to the plan is drawn as a loop; done leads on", () => {
  const view = {
    flow_id: "f", key: "team-delivery", title: "Team delivery", status: "published", version_id: "v", version: 2,
    version_status: "published", published_version: 2, editable: true, composite: false, definition: {},
    validation_report: { valid: true, errors: [] }, layout: {},
    nodes: [
      { id: "start", kind: "start", title: "Start" },
      { id: "plan", kind: "phase", title: "Plan the work", agent: "coordinator", checks: 1 },
      { id: "build", kind: "parallel_work", title: "Build the story", config: { plan: "plan", roles: ROLES } },
      { id: "pipeline", kind: "platform_action", title: "CI pipeline", action: "pipeline.run" },
      { id: "done", kind: "outcome", title: "Done", outcome: "done" },
    ],
    edges: [
      { id: "e0", source: "start", target: "plan", kind: "next", when: null, max_iterations: null, title: "" },
      { id: "e1", source: "plan", target: "build", kind: "next", when: null, max_iterations: null, title: "" },
      { id: "e2", source: "build", target: "pipeline", kind: "next", when: "done", max_iterations: null, title: "" },
      { id: "e3", source: "build", target: "plan", kind: "loop", when: "replan", max_iterations: 3, title: "Replan" },
      { id: "e4", source: "pipeline", target: "done", kind: "next", when: "succeeded", max_iterations: null, title: "" },
    ],
  };
  const graph = buildPhasedGraph(view);
  const box = graph.boxes.find((item) => item.id === "build");
  assert.equal(box.family, "parallel");
  const arrows = drawnArrows(graph);
  const replan = arrows.find((arrow) => arrow.source === "build" && arrow.target === "plan");
  assert.ok(replan && replan.loop && !replan.badge, "replan is its own loop arrow");
  const { positions } = layoutPhasedGraph(graph);
  assert.ok(positions.get("build").y > positions.get("plan").y && positions.get("pipeline").y > positions.get("build").y,
    "plan, parallel work and the pipeline stand top to bottom");
});

test("while editing, two exits of one box to the same target both name all their routes", () => {
  const view = {
    nodes: [
      { id: "ready", kind: "user_confirmation", title: "Ready?", subject: "advance" },
      { id: "build", kind: "parallel_work", title: "Build", config: { roles: ROLES } },
    ],
    edges: [
      { id: "a", source: "ready", target: "build", kind: "next", when: "confirmed", max_iterations: null, title: "" },
      { id: "b", source: "ready", target: "build", kind: "next", when: "changed", max_iterations: null, title: "" },
    ],
  };
  const editing = buildPhasedGraph(view, { editing: true }).arrows.filter((arrow) => arrow.source === "ready");
  assert.deepEqual(editing.map((arrow) => [arrow.id, arrow.label]),
    [["a", "confirmed or changes asked"], ["b", "confirmed or changes asked"]]);
  const reading = buildPhasedGraph(view).arrows.filter((arrow) => arrow.source === "ready");
  assert.deepEqual(reading.map((arrow) => [arrow.edgeIds, arrow.label]), [[["a", "b"], "confirmed or changes asked"]]);
});

test("a new Parallel work box starts with the three usual roles, each an agent step that may change code", async () => {
  const { defaultConfig } = await import("../../src/admin/components/agentsWorkflows/canvas/designer/inspector/nodeDefaults.ts");
  const config = defaultConfig("parallel_work");
  assert.deepEqual(Object.keys(config.roles), ["backend", "frontend", "test"]);
  assert.equal(config.roles.backend.workflow_contract.capability_class, "change");
  assert.equal(config.parallel, true);
  assert.notEqual(config.roles.backend, config.roles.frontend, "each role its own object");
});
