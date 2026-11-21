// Workflow designer on the page: the list's "New workflow" starts an empty canvas in the designer (its own page
// key for the help), test fixtures stay hidden unless asked for, one date form in the list (W10), the problem list
// names its box, and the editor uses the agreed test ids and the side panel's inspectors.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { liveIssues, mergedIssues } from "../../src/admin/components/agentsWorkflows/canvas/designer/issues.ts";
import { addNode, connect } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelEditing.ts";
import { fromDefinition } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelDefinition.ts";
import {
  designerCatalogPath, designerEditable, designerStatus, publishProblem,
} from "../../src/admin/components/agentsWorkflows/canvas/phasedWorkflowModel.ts";
import { ageLabel, filterListed, listedWorkflows } from "../../src/admin/components/agentsWorkflows/workflows/workflowListModel.ts";
import { readWorkflowsOverview } from "../../src/admin/components/agentsWorkflows/workflows/workflowsModel.ts";
import { listAdminAreaTabRefs, resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";

const read = (path) => fs.readFileSync(new URL(`../../src/admin/components/agentsWorkflows/${path}`, import.meta.url), "utf8");
const CATALOG = {
  agents: [{ key: "engineer", name: "Engineer", capability_ceiling: "deliver" }], tools: [], checkTypes: [], gateCheckTypes: [],
  workflows: [], platformActions: [], confirmationSubjects: ["advance"], watchConditions: [], outcomes: ["done", "stopped"],
  deciders: ["requester"],
};
const STARTER = {
  execution_kind: "phased",
  nodes: [{ id: "start", type: "start", label: "Start", config: {} }, { id: "end", type: "outcome", label: "Done", config: { outcome: "done" } }],
  edges: [{ id: "e-start", source_node_id: "start", target_node_id: "end" }],
};

test("Test fixtures are hidden until 'Show test flows'; the list says how long ago in one form", () => {
  const overview = readWorkflowsOverview({
    usage_window_days: 30, workflows: [],
    flows: [
      { flow_id: "f1", key: "companion", title: "Companion acceptance fixture", execution_kind: "phased", test_flow: true, status: "published" },
      { flow_id: "f2", key: "release", title: "Release notes", execution_kind: "phased", test_flow: false, status: "draft" },
    ],
  });
  const items = listedWorkflows(overview);
  const base = { query: "", capability: "", scope: "all", kind: "all" };
  assert.deepEqual(filterListed(items, base).map((item) => item.key), ["release"]);
  assert.deepEqual(filterListed(items, { ...base, showTestFlows: true }).map((item) => item.key), ["companion", "release"]);
  const now = Date.parse("2026-11-09T12:00:00Z");
  assert.deepEqual(
    ["2026-11-09T09:00:00Z", "2026-11-06T12:00:00Z", "2026-10-15T12:00:00Z", "2026-06-01T12:00:00Z", "2023-01-01T00:00:00Z", null]
      .map((value) => ageLabel(value, now)),
    ["3 h ago", "3 d ago", "25 d ago", "5 mo ago", "3 y ago", "—"],
  );
});

test("the designer is its own page under Workflows, with its own help", () => {
  assert.equal(resolveAdminAreaForTab("workflowDesigner"), resolveAdminAreaForTab("workflowList"));
  assert.ok(listAdminAreaTabRefs(resolveAdminAreaForTab("workflowList")).some((ref) => ref.id === "workflowDesigner"));
  assert.ok(fs.existsSync(new URL("../../help/workflows/workflowDesigner.md", import.meta.url)));
  const page = read("workflows/WorkflowsPage.tsx");
  assert.match(page, /data-testid="designer-new"[\s\S]*?>\s*New workflow\s*</, "the list's button says New workflow");
  assert.match(page, /PHASED_CREATE_PATH/);
  assert.match(page, /openAdminTab\("workflowDesigner"\)/);
});

test("a draft opens in the designer; a published or composite version stays read only with Edit as draft", () => {
  assert.equal(designerEditable({ editable: true, version_status: "draft", composite: false }), true);
  assert.equal(designerEditable({ editable: true, version_status: "published", composite: false }), false);
  assert.equal(designerEditable({ editable: true, version_status: "draft", composite: true }), false);
  assert.equal(designerEditable({ editable: false, version_status: "draft" }), false);
  assert.deepEqual(["draft", "published", "in_review"].map((version_status) => designerStatus({ version_status })), ["draft", "published", "in review"]);
  assert.equal(designerStatus({ version_status: "draft", review_state: "awaiting_approval" }), "in review");
  const fourEyes = Object.assign(new Error("A workflow version is published by an admin other than its author"), { code: "workflow_four_eyes" });
  assert.match(publishProblem(fourEyes, "x"), /Request publishing/);
  assert.equal(publishProblem(new Error("Boom"), "x"), "Boom");
  assert.equal(designerCatalogPath("ws 1"), "/api/v1/phased-workflows/catalog?project_id=ws%201");
  const editor = ["PhasedWorkflowEditor.tsx", "PhasedEditorHeader.tsx"].map((name) => read(`canvas/${name}`)).join("\n");
  assert.match(editor, />Edit as draft</);
  assert.match(editor, /<DesignerEditor /);
});

test("the editor wires the agreed test ids, the inspectors and the keyboard", () => {
  const editor = ["DesignerEditor.tsx", "DesignerHeader.tsx", "DesignerToolbar.tsx", "DesignerIssues.tsx", "DesignerBoxMenu.tsx", "designerSidePanel.tsx",
    "designerPublishing.ts", "useDesignerShortcuts.ts"].map((name) => read(`canvas/designer/${name}`)).join("\n");
  for (const id of ["designer", "designer-name", "designer-save-draft", "designer-validation", "designer-issue", "designer-status",
    "designer-request-publish", "designer-connect-to", "designer-connect-target"]) {
    assert.match(editor, new RegExp(`data-testid="${id}"`), id);
  }
  assert.match(editor, /data-testid="designer-request-publish"\s+disabled=\{busy \|\| Boolean\(requestBlocked\)\}/);
  assert.match(editor, /flowReviewPath\(view\.version_id\)/);
  assert.match(editor, /<NodeInspector [\s\S]{0,600}onRoute=\{\(when, target\) => change\(\(current\) => route\(/, "a condition's routes go into the model");
  assert.match(editor, /<EdgeInspector /);
  assert.match(editor, /<SidePanel mode="page" title=\{node\.label \|\| kindName\(node\.type\)\} subtitle=\{kindName\(node\.type\)\}/);
  for (const label of ["Undo", "Redo", "Copy", "Delete", "Group", "Ungroup", "Save draft", "Request publishing", "Connect to…"]) {
    assert.match(editor, new RegExp(`>${label}<`), label);
  }
  assert.match(editor, /mod && key === "z"/);
  const canvas = ["canvas/PhasedCanvas.tsx", "canvas/PhasedCanvasNodes.tsx"].map(read).join("\n");
  for (const id of ["designer-node", "designer-port-out", "designer-node-menu", "designer-edge", "designer-canvas"]) {
    assert.match(canvas, new RegExp(`"${id}"`), id);
  }
  assert.match(canvas, /screenToFlowPosition/);
  assert.match(read("canvas/designer/DesignerCatalogPanel.tsx"), /data-testid="designer-catalog-item" data-kind=\{kind\}/);
});

test("the problem list: live problems name their box, the report adds what the panel cannot see, nothing twice", () => {
  let model = fromDefinition(structuredClone(STARTER));
  assert.deepEqual(liveIssues(model, CATALOG), []);
  const added = addNode(model, "phase");
  model = added.model;
  const live = liveIssues(model, CATALOG);
  assert.ok(live.some((issue) => issue.nodeId === "step-1" && issue.message === "“Agent step”: Choose the agent that does this step."));
  assert.ok(live.some((issue) => issue.nodeId === "step-1" && /needs an arrow to the next box/.test(issue.message)));
  model = connect(model, "step-1", "end", null, CATALOG).model;
  assert.equal(liveIssues(model, CATALOG).some((issue) => /needs an arrow/.test(issue.message)), false);
  const report = [
    { code: "phase_without_agent", message: "Phase 'step-1' must name its agent.", node_id: "step-1" },
    { code: "consumer_without_producer", message: "“Agent step” reads a test contract nobody submits.", node_id: "step-1" },
    { code: "gate_without_checks", message: "“Gone” needs at least one check.", node_id: "gone" },
    { code: "cycle_without_loop_edge", message: "Arrows go round in a circle." },
  ];
  const merged = mergedIssues(liveIssues(model, CATALOG), report, model);
  const fromReport = merged.filter((issue) => issue.key.startsWith("r:"));
  assert.deepEqual(fromReport.map((issue) => [issue.message, issue.nodeId]), [
    ["“Agent step” reads a test contract nobody submits.", "step-1"],
    ["Arrows go round in a circle.", undefined],
  ]);
});
