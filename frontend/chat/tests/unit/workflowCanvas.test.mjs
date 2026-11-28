// One concept Workflow: one list as the entry and a selected workflow opened on the canvas in the whole window
// (designer D2a), links land on the right workflow, and a phase of a workflow is edited as a graph whose edits only
// touch its stored steps and checks.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addCheck, addStep, canvasEdges, canvasNode, insertNode, moveNode, newCheck, newStep, patchNode, readStepsGraphView, removeNode,
  updateCheck, updateStep,
} from "../../src/admin/components/agentsWorkflows/canvas/stepsGraphModel.ts";
import {
  filterListed, lastChangedLabel, listUrl, listedWorkflows, readListView, readOpenWorkflow,
} from "../../src/admin/components/agentsWorkflows/workflows/workflowListModel.ts";
import { readWorkflowsOverview } from "../../src/admin/components/agentsWorkflows/workflows/workflowsModel.ts";

const OVERVIEW = readWorkflowsOverview({
  usage_window_days: 30,
  flows: [{
    flow_id: "f0", key: "knowledge-request", title: "Knowledge", capability_class: "read_only", node_count: 4,
    execution_kind: "phased", scope: "Global", project_id: null, used: 4, status: "published", version: 2,
    updated_at: "2026-11-09T08:00:00Z", updated_by: "Ada Admin",
  }, {
    flow_id: "f1", key: "incident-intake", title: "Incident intake", capability_class: "read_only", node_count: 5,
    scope: "Claims", project_id: "ws", used: 1, status: "draft", version: 3,
  }, {
    flow_id: "f2", key: "bug-fix", title: "Bug fix", node_count: 21, execution_kind: "phased", used: 6, status: "published",
    version: 4, updated_at: "2026-10-15T09:30:00", updated_by: "Fay Editor",
  }],
});

test("the list filters by class, scope and text", () => {
  const items = listedWorkflows(OVERVIEW);
  assert.deepEqual(items.map((item) => item.key), ["knowledge-request", "incident-intake", "bug-fix"]);
  const all = { query: "", capability: "", scope: "all" };
  assert.deepEqual(filterListed(items, { ...all, scope: "workspace" }).map((item) => item.id), ["f1"]);
  assert.deepEqual(filterListed(items, { ...all, scope: "global" }).map((item) => item.id), ["f0", "f2"]);
  assert.deepEqual(filterListed(items, { ...all, capability: "read_only" }).map((item) => item.id), ["f0", "f1"]);
  assert.deepEqual(filterListed(items, { ...all, query: "knowledge" }).map((item) => item.id), ["f0"]);
  assert.deepEqual(filterListed(items, { ...all, query: "incident" }).map((item) => item.id), ["f1"]);
});

test("the list is the entry; a link that names a workflow opens it directly", () => {
  assert.equal(readListView("?tab=workflowList"), "table");
  assert.equal(readListView("?tab=workflowList&view=table"), "table");
  // An old Canvas link without a workflow lands on the list, not on some first workflow.
  assert.equal(readListView("?tab=workflowList&view=canvas"), "table");
  assert.equal(readListView("?view=canvas&phased=f2"), "canvas");
  // The retired flow builder's addresses open nothing.
  for (const search of ["?tab=workflowList&flow_id=f1", "?view=canvas&new_flow=1"]) {
    assert.equal(readListView(search), "table", search);
  }
  assert.equal(readOpenWorkflow("?phased=f2"), "f2");
  assert.equal(
    listUrl("https://octryx.example/chat?area=workflows&tab=workflowList#x", "canvas", "f2"),
    "/chat?area=workflows&tab=workflowList&view=canvas&phased=f2#x",
  );
  assert.equal(listUrl("https://octryx.example/chat?tab=workflowList&phased=f2", "table", null), "/chat?tab=workflowList&view=table");
});

const VIEW = readStepsGraphView({
  key: "k#n1", title: "K · Build", status: "published", version_id: "v2", version: 2, version_status: "published",
  editable: true, check_types: ["tool_called", "judge"], advisory_check_types: ["judge"], step_modes: ["strict", "guided"],
  validation_report: { valid: false, errors: [{ code: "e1", message: "A step needs a tool." }], warnings: [] },
  graph: {
    capability_class: "change",
    nodes: [
      { id: "start", kind: "start", derived: true },
      { id: "approval-class", kind: "approval", derived: true, reason: "capability_class", capability_class: "change" },
      { id: "step-0", kind: "step", step: { tool: "a", args: { x: 1 } }, tool: "a", mode: "strict", allowed: true },
      { id: "step-1", kind: "step", step: { tool: "b", mode: "guided" }, tool: "b", mode: "guided", allowed: false },
      { id: "check-0", kind: "check", check: { type: "tool_called", blocking: true }, type: "tool_called", blocking: true },
      { id: "result", kind: "result", derived: true },
      { id: "x", kind: "unknown" },
    ],
  },
});

test("the graph view is read with its vocabularies; unknown node kinds are dropped", () => {
  assert.deepEqual(VIEW.report, { valid: false, errors: [{ code: "e1", message: "A step needs a tool." }], warnings: [] });
  assert.deepEqual(VIEW.graph.nodes.map((node) => node.id), ["start", "approval-class", "step-0", "step-1", "check-0", "result"]);
  assert.deepEqual(VIEW.advisoryCheckTypes, ["judge"]);
});

test("canvas edits change only the stored entries and their order; derived nodes stay", () => {
  const nodes = VIEW.graph.nodes;
  const step = addStep(nodes, "c");
  assert.deepEqual(step.nodes.map((node) => node.kind), ["start", "approval", "step", "step", "step", "check", "result"]);
  assert.deepEqual(step.nodes[4].step, { tool: "c" });
  const check = addCheck(nodes, "judge");
  assert.deepEqual(check.nodes.at(-2).check, { type: "judge", blocking: false, description: "" });
  assert.deepEqual(moveNode(nodes, "step-1", -1).map((node) => node.id).slice(2, 4), ["step-1", "step-0"]);
  assert.equal(moveNode(nodes, "step-0", -1), nodes, "the first step does not move past derived nodes");
  assert.equal(moveNode(nodes, "start", 1), nodes, "derived nodes never move");
  assert.equal(removeNode(nodes, "approval-class").length, nodes.length, "derived nodes are not removable");
  assert.deepEqual(removeNode(nodes, "step-0").map((node) => node.id), ["start", "approval-class", "step-1", "check-0", "result"]);
  const strict = updateStep(nodes, "step-1", { mode: "strict" });
  assert.deepEqual(strict[3].step, { tool: "b", mode: "strict" });
  assert.deepEqual(updateStep(nodes, "step-1", { mode: undefined })[3].step, { tool: "b" }, "class default removes the key");
  assert.deepEqual(updateStep(nodes, "step-0", { evidence_label: "x" })[2].step, { tool: "a", args: { x: 1 }, evidence_label: "x" });
  assert.deepEqual(updateCheck(nodes, "check-0", { blocking: false })[4].check, { type: "tool_called", blocking: false });
});

test("nodes render on the flow builder's node with mode, policy and blocking badges, chained in order", () => {
  const [start, approval, strict, guided, check, result] = VIEW.graph.nodes.map(canvasNode);
  assert.deepEqual([start.type, approval.type, strict.type, check.type, result.type], ["trigger", "approval", "tool_step", "evaluation", "output"]);
  assert.equal(approval.label, "User confirms first");
  assert.deepEqual(strict.badges.map((badge) => badge.label), ["Strict"]);
  assert.deepEqual(guided.badges.map((badge) => badge.label), ["Guided", "Not in tool policy"]);
  assert.deepEqual(check.badges, [{ label: "Blocking", kind: "danger" }]);
  assert.deepEqual(canvasEdges(VIEW.graph.nodes).map((edge) => edge.id).slice(0, 2), ["start->approval-class", "approval-class->step-0"]);
});

test("the list says when a workflow last changed, by whom and how often it ran", () => {
  const [recent, unchanged, phased] = listedWorkflows(OVERVIEW);
  const now = Date.parse("2026-11-09T11:00:00Z");
  assert.deepEqual([recent.row.updatedBy, phased.row.updatedBy, unchanged.row.updatedBy], ["Ada Admin", "Fay Editor", null]);
  assert.equal(lastChangedLabel(recent, now).text, "3 h ago");
  assert.equal(lastChangedLabel(phased, now).text, "25 d ago", "a naive server time is UTC; always how long ago (W10)");
  assert.match(lastChangedLabel(phased, now).title, /15 Oct 2026, \d\d:30:00/);
  assert.deepEqual(lastChangedLabel(unchanged, now), { text: "—", title: "" });
  assert.equal(phased.row.used, 6);
});

test("One list as the entry, a selected workflow fills the window with one way back and one view", async () => {
  const fs = await import("node:fs");
  const read = (path) => fs.readFileSync(new URL(`../../src/admin/components/${path}`, import.meta.url), "utf8");
  const page = read("agentsWorkflows/workflows/WorkflowsPage.tsx");
  assert.doesNotMatch(page, /aria-label="Workflow on the canvas"/, "no dropdown to switch workflows");
  assert.doesNotMatch(page, /label: "Canvas"|label: "Table"/, "no Canvas / Table toggle");
  assert.doesNotMatch(page, /WorkflowDetailDrawer row=\{selected\}/, "a row never opens the drawer");
  // A workflow opens in the designer page (openWorkflow switches to it).
  assert.match(page, /const openItem = \(item: ListedWorkflow\) => leave\(\(\) => openWorkflow\(item\.id\)\);/);
  assert.doesNotMatch(page, /StepsWorkflowEditor/, "a phase opens from its workflow, never from the list");
  assert.match(page, /<PhasedWorkflowEditor [^>]*onBack=\{toList\}/);
  assert.doesNotMatch(page, /FlowWorkflowEditor|New flow|newFlow/, "no path to the retired flow builder");
  // The filters beyond search fold away.
  assert.match(page, /aria-controls="workflows-filters"/);
  const table = read("agentsWorkflows/workflows/WorkflowTable.tsx");
  assert.match(table, /<th>Workflow<\/th><th>Status<\/th>\{onToggleActive \? <th>On<\/th> : null\}<th>Last changed<\/th><th>By<\/th><th>\{runs\}<\/th>/);
  assert.match(read("agentsWorkflows/canvas/PhasedEditorHeader.tsx"), /← All workflows/);
  assert.match(read("agentsWorkflows/canvas/StepsEditorHeader.tsx"), /← Phases/);
  assert.match(read("agentsWorkflows/canvas/PhasedWorkflowEditor.tsx"), /<StepsWorkflowEditor graphPath=\{phaseGraphPath\(flowId, openPhase\)\}/);
  const phased = ["PhasedWorkflowEditor.tsx", "PhasedCanvasToolbar.tsx"].map((name) => read(`agentsWorkflows/canvas/${name}`)).join("\n");
  assert.doesNotMatch(phased, /SegmentedTabs|label: "Diagram"|label: "List"/, "the canvas is the only view");
  assert.match(phased, /aria-controls="phased-legend"/, "the legend folds away");
});

test("the list and the phase editor name the shown version's state", async () => {
  const { stepsStatusLabel } = await import("../../src/admin/components/agentsWorkflows/canvas/stepsGraphModel.ts");
  const { statusLabel } = await import("../../src/admin/components/agentsWorkflows/workflows/workflowsModel.ts");
  assert.equal(statusLabel({ status: "published", version: 1 }), "Published v1");
  assert.equal(statusLabel({ status: "draft", version: 3 }), "Draft v3");
  assert.equal(statusLabel({ status: "archived", version: 2 }), "Archived");
  assert.equal(stepsStatusLabel({ status: "published", version: 2, versionStatus: "published" }), "Published v2");
  assert.equal(stepsStatusLabel({ status: "draft", version: 3, versionStatus: "draft" }), "Draft v3");
});

test("test flows stay hidden unless asked for; leaving dirty edits waits for the confirm dialog", async () => {
  const { requestLeave } = await import("../../src/admin/components/agentsWorkflows/workflows/workflowListModel.ts");
  const overview = readWorkflowsOverview({
    flows: [
      { flow_id: "f1", key: "incident-intake", title: "Incident intake", test_flow: false },
      { flow_id: "f2", key: "test-flow-1", title: "Smoke", test_flow: true },
    ],
  });
  const items = listedWorkflows(overview);
  const all = { query: "", capability: "", scope: "all" };
  assert.deepEqual(filterListed(items, all).map((item) => item.id), ["f1"]);
  assert.deepEqual(filterListed(items, { ...all, showTestFlows: true }).map((item) => item.id), ["f1", "f2"]);

  const ran = [];
  assert.equal(requestLeave(false, () => ran.push("clean")), null);
  const pending = requestLeave(true, () => ran.push("dirty"));
  assert.deepEqual(ran, ["clean"], "a dirty editor does not leave before the confirmation");
  pending();
  assert.deepEqual(ran, ["clean", "dirty"]);
});

test("the page asks with the design-system ConfirmDialog; a phase saves drafts and never publishes", async () => {
  const fs = await import("node:fs");
  const read = (path) => fs.readFileSync(new URL(`../../src/admin/components/${path}`, import.meta.url), "utf8");
  const page = read("agentsWorkflows/workflows/WorkflowsPage.tsx");
  assert.match(page, /<ConfirmDialog title="Leave this workflow\?"/);
  assert.match(page, /const toList = \(\) => leave\(/, "going back to the list waits for unsaved edits");
  assert.match(page, /onDirtyChange=\{setDirty\}/);
  assert.doesNotMatch(page, /window\.confirm/);
  const editor = ["StepsWorkflowEditor.tsx", "StepsWorkflowPanels.tsx", "stepsWorkflowState.ts"]
    .map((name) => read(`agentsWorkflows/canvas/${name}`)).join("\n");
  assert.doesNotMatch(editor, />Publish|approvalId|\/publish/);
  assert.match(editor, /void saveStepsDraft\(context\)/);
});

test("a new check or step is a side-panel draft and joins the workflow only on confirm", async () => {
  const nodes = VIEW.graph.nodes;
  const draft = patchNode(newCheck("tool_called"), { type: "evidence_count", params: { tools: ["search"] } });
  assert.deepEqual(draft.check, { type: "evidence_count", blocking: false, description: "", params: { tools: ["search"] } });
  assert.deepEqual(nodes.map((node) => node.id), ["start", "approval-class", "step-0", "step-1", "check-0", "result"],
    "preparing the draft leaves the workflow as it is");
  const added = insertNode(nodes, draft);
  assert.equal(added.at(-2), draft, "a new check goes before the result");
  const step = patchNode(newStep(""), { tool: "c" });
  assert.equal(insertNode(nodes, step)[4], step, "a new step goes after the last step");
  assert.deepEqual(step.step, { tool: "c" });

  const fs = await import("node:fs");
  const read = (path) => fs.readFileSync(new URL(`../../src/admin/components/agentsWorkflows/canvas/${path}`, import.meta.url), "utf8");
  const editor = ["StepsWorkflowEditor.tsx", "StepsWorkflowPanels.tsx", "stepsWorkflowState.ts"].map(read).join("\n");
  assert.doesNotMatch(editor, /FlowInspectorPanel/, "no inline step settings beside the canvas");
  assert.match(editor, /setAdding\(newCheck\(/, "+ Check opens the panel with a draft, the workflow is not edited");
  assert.match(editor, /edit\(insertNode\(nodes, adding\), null\)/, "Add check inserts the draft");
  assert.match(editor, /<SidePanel[\s\S]*testId="steps-add-panel"/);
  assert.match(editor, /<SidePanel[\s\S]*testId="steps-node-panel"/);
  const inspector = read("StepsInspector.tsx");
  assert.doesNotMatch(inspector, /knowledge_search|jira_get_issue/, "no raw tool ids as placeholder");
  assert.doesNotMatch(inspector, />Move earlier</, "moving and removing are the panel's actions");
});

test("a listed workflow carries its On/Off; a row without is_active reads as on", () => {
  const overview = readWorkflowsOverview({ flows: [
    { flow_id: "f1", key: "pr-fix", title: "PR fix", is_active: false },
    { flow_id: "f2", key: "bug-fix-reproduction", title: "Bug fix" },
  ] });
  assert.deepEqual(overview.flows.map((row) => [row.key, row.isActive]), [["pr-fix", false], ["bug-fix-reproduction", true]]);
});
