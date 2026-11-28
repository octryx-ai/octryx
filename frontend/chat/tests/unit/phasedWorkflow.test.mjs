// Workflows that run in phases: their address in the Workflows list, and the editor's reading of a phased graph (node
// lines, exits, bounded loops, publishability).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  exitsOf, loopLine, nodeDetail, phaseGraphPath, publishable,
} from "../../src/admin/components/agentsWorkflows/canvas/phasedWorkflowModel.ts";
import {
  filterListed, listUrl, listedWorkflows, readOpenWorkflow,
} from "../../src/admin/components/agentsWorkflows/workflows/workflowListModel.ts";
import { readWorkflowsOverview } from "../../src/admin/components/agentsWorkflows/workflows/workflowsModel.ts";

const OVERVIEW = readWorkflowsOverview({
  workflows: [],
  flows: [
    { flow_id: "f1", key: "triage", title: "Triage", node_count: 3, status: "draft", version: 1, execution_kind: "phased" },
    { flow_id: "f2", key: "phased", title: "Phased", node_count: 4, status: "published", version: 2, execution_kind: "phased" },
  ],
});

test("every listed workflow is opened by its `phased` address", () => {
  const items = listedWorkflows(OVERVIEW);
  assert.deepEqual(items.map((item) => item.id), ["f1", "f2"]);
  assert.deepEqual(filterListed(items, { query: "phas", capability: "", scope: "all" }).map((item) => item.id), ["f2"]);
  assert.equal(readOpenWorkflow("?phased=f2"), "f2");
  assert.equal(readOpenWorkflow("?flow_id=f1"), null, "the retired flow builder address opens nothing");
  assert.equal(listUrl("https://x.test/admin?phased=f1", "canvas", "f2"), "/admin?phased=f2&view=canvas");
});

const NODES = [
  { id: "work", kind: "phase", title: "Implement", capability_class: "change", steps: 1, checks: 2, path_rules: ["tests/**"] },
  { id: "green", kind: "gate", title: "Tests green", checks: 1 },
  { id: "done", kind: "outcome", title: "Done", outcome: "done" },
];
const EDGES = [
  { id: "e1", source: "work", target: "green", kind: "next", when: null, max_iterations: null, title: "" },
  { id: "e2", source: "green", target: "done", kind: "next", when: "passed", max_iterations: null, title: "" },
  { id: "e3", source: "green", target: "work", kind: "loop", when: "failed", max_iterations: 3, title: "Fix" },
];

test("the editor names each node, its exits and every bounded loop", () => {
  assert.equal(nodeDetail(NODES[0]), "change · 1 steps · 2 checks · writes only tests/**");
  assert.deepEqual(exitsOf(NODES[1], EDGES, NODES), ["passed → Done"]);
  assert.equal(loopLine(EDGES[2], NODES), "Fix: back to Implement (on failed) · at most 3");
  assert.equal(phaseGraphPath("f 2", "work"), "/api/v1/phased-workflows/f%202/phases/work/graph");
  const view = { editable: true, version_status: "draft", validation_report: { valid: true, errors: [], warnings: [] } };
  assert.equal(publishable(view), true);
  assert.equal(publishable({ ...view, validation_report: { valid: false, errors: [], warnings: [] } }), false);
});
