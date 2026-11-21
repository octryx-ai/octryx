// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminFlowRenderGuards2.test.mjs
//
// Render guards for the flow canvas, the Flow Builder editor, the phase steps and phased workflow editors and the admin
// panel switch: each is rendered with representative props and its key structure is asserted, so splitting these
// components into smaller parts keeps what they draw. React Flow is replaced by a light stand-in that renders its
// props as data attributes.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { test } from "node:test";
import { createElement } from "react";
import { TestRenderer, act, buttons, byTestId, flush, loader, text, windowStub, xyflow } from "./adminFlowRenderHarness.mjs";

// --- Phase steps editor --------------------------------------------------------------------------------------------

const STEPS_VIEW = {
  key: "k", title: "Knowledge routing", status: "draft", version_id: "v2", version: 2, version_status: "draft",
  editable: true, check_types: ["tool_called", "judge"], advisory_check_types: ["judge"], step_modes: ["strict", "guided"],
  validation_report: { valid: true, errors: [], warnings: [{ code: "w1", message: "One step has no description." }] },
  graph: {
    capability_class: "change",
    nodes: [
      { id: "start", kind: "start", derived: true },
      { id: "step-0", kind: "step", step: { tool: "search" }, tool: "search", mode: "strict", allowed: true },
      { id: "check-0", kind: "check", check: { type: "tool_called", blocking: true }, type: "tool_called", blocking: true },
      { id: "result", kind: "result", derived: true },
    ],
  },
};

async function renderStepsEditor() {
  const load = loader({ window: windowStub() }, { "@xyflow/react": xyflow });
  const { StepsWorkflowEditor } = load("admin/components/agentsWorkflows/canvas/StepsWorkflowEditor.tsx");
  const readJson = async (url) => (url.includes("tool-catalog") ? [{ name: "search" }, { name: "fetch" }] : STEPS_VIEW);
  let view;
  await act(async () => { view = TestRenderer.create(createElement(StepsWorkflowEditor, { graphPath: "/api/v1/phased-workflows/f-1/phases/n-1/graph", readJson, onBack: () => {} })); });
  await flush();
  return view;
}

test("the steps editor shows the header, the issues, the canvas with its toolbar and opens the add panel", async () => {
  const view = await renderStepsEditor();
  const root = view.root;
  assert.equal(byTestId(root, "steps-workflow-editor").length, 1);
  assert.deepEqual(root.findAll((node) => node.type === "ul" && node.props["aria-label"] === "Validation").map(text),
    ["One step has no description."]);
  assert.equal(byTestId(root, "steps-add-step").length, 1);
  assert.equal(byTestId(root, "steps-add-check").length, 1);
  assert.equal(byTestId(root, "steps-add-panel").length, 0);
  act(() => byTestId(root, "steps-add-check")[0].props.onClick());
  assert.equal(byTestId(root, "steps-add-panel").length, 1);
  assert.equal(byTestId(root, "steps-add-confirm")[0].props.disabled, false);
  assert.match(text(byTestId(root, "steps-add-confirm")[0]), /Add check/);
  act(() => byTestId(root, "steps-add-confirm")[0].props.onClick());
  assert.equal(byTestId(root, "steps-add-panel").length, 0);
  assert.ok(root.findAll((node) => node.type === "p" && node.props.role === "status")
    .some((node) => /Unsaved changes — save them as a draft version of the workflow\./.test(text(node))));
  act(() => view.unmount());
});

// --- Phased workflow designer --------------------------------------------------------------------------------------

const PHASED_VIEW = {
  flow_id: "f-2", key: "release", title: "Release notes", status: "draft", version_id: "pv-1", version: 4, version_status: "draft",
  published_version: 3, editable: true, nodes: [], edges: [], project_id: null,
  validation_report: { valid: false, errors: [{ code: "x", message: "The flow needs an outcome." }], warnings: [] },
  definition: {
    execution_kind: "phased",
    nodes: [{ id: "start", type: "start", label: "Start", config: {} }, { id: "end", type: "outcome", label: "Done", config: { outcome: "done" } }],
    edges: [{ id: "e-start", source_node_id: "start", target_node_id: "end" }],
  },
};

test("the designer shows its name, status, actions, problems, catalog and canvas", async () => {
  const load = loader({ window: windowStub() }, { "@xyflow/react": xyflow });
  const { DesignerEditor } = load("admin/components/agentsWorkflows/canvas/designer/DesignerEditor.tsx");
  const dirty = [];
  const readJson = async () => ({ agents: [], tools: [], checkTypes: [], gateCheckTypes: [], workflows: [], platformActions: [],
    confirmationSubjects: [], watchConditions: [], outcomes: ["done", "stopped"], deciders: ["requester"] });
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(DesignerEditor, { view: PHASED_VIEW, readJson, onView: () => {}, onReload: async () => {},
      onDirtyChange: (value) => dirty.push(value), onBack: () => {}, onOpenPhase: () => {} }));
  });
  await flush();
  const root = view.root;
  assert.equal(byTestId(root, "designer").length, 1);
  assert.equal(byTestId(root, "designer-name")[0].props.value, "Release notes");
  assert.equal(byTestId(root, "designer-status")[0].props["data-status"], "draft");
  assert.equal(byTestId(root, "designer-save-draft")[0].props.disabled, true, "nothing to save yet");
  assert.equal(byTestId(root, "designer-request-publish")[0].props.disabled, true);
  assert.ok(buttons(root).includes("← All workflows"));
  assert.ok(buttons(root).includes("Publish"));
  assert.equal(root.findAll((node) => node.props.className === "dsg").length, 1);
  assert.ok(byTestId(root, "designer-catalog-item").length > 0);
  assert.equal(dirty.at(-1), false);
  act(() => byTestId(root, "designer-name")[0].props.onChange({ target: { value: "Release notes v2" } }));
  assert.equal(byTestId(root, "designer-save-draft")[0].props.disabled, false);
  assert.equal(dirty.at(-1), true);
  act(() => view.unmount());
});

test("a published phased workflow shows its header, issues, read-only canvas and toolbar", async () => {
  const load = loader({ window: windowStub() }, { "@xyflow/react": xyflow });
  const { PhasedWorkflowEditor } = load("admin/components/agentsWorkflows/canvas/PhasedWorkflowEditor.tsx");
  const published = {
    ...PHASED_VIEW, version_status: "published", editable: false,
    nodes: [
      { id: "start", kind: "start", title: "Start" },
      { id: "build", kind: "phase", title: "Build", steps: 2, checks: 1 },
      { id: "end", kind: "outcome", title: "Done", outcome: "done" },
    ],
    edges: [
      { id: "e1", source: "start", target: "build", kind: "next", when: null, max_iterations: null, title: "" },
      { id: "e2", source: "build", target: "end", kind: "result", when: "done", max_iterations: null, title: "done" },
    ],
    validation_report: { valid: true, errors: [], warnings: [{ code: "w", message: "No owner is named." }] },
  };
  const dirty = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(PhasedWorkflowEditor, { flowId: "f-2", readJson: async () => published,
      onDirtyChange: (value) => dirty.push(value), onBack: () => {} }));
  });
  await flush();
  const root = view.root;
  assert.equal(byTestId(root, "designer").length, 1);
  assert.ok(buttons(root).includes("← All workflows"));
  assert.match(text(root.find((node) => node.props["aria-label"] === "Validation")), /No owner is named\./);
  assert.equal(byTestId(root, "rf")[0].props["data-nodes"].split(",").length, 3);
  assert.equal(dirty.at(-1), false);
  const lines = [JSON.stringify(view.toJSON())];
  const digest = crypto.createHash("sha256").update(lines.join("\n")).digest("hex");
  assert.equal(digest, "8e9f780abe62c881b4c59619f39494ca22029742bacbded37cb5c37bfd536f71");
  act(() => view.unmount());
});

// --- Admin panel switch --------------------------------------------------------------------------------------------

const TABS = ["adminProblems", "adminConnections", "platformVersion", "platformDevices", "restApis", "restApiCalls", "plugins",
  "users", "workRoles", "workRoleFunctions", "workRoleAudit", "identityRoles", "identityGroups", "identityProviders",
  "identityAccess", "projects", "backupRestore", "policies", "researchPolicies", "providers",
  "modelCatalog", "modelsOverview", "modelOrder", "runtimePolicyLists", "runtimeExecution", "commandSafety", "contentSecurity",
  "classificationPolicy", "approvalRule", "cedarPolicies", "policyTestBench", "runtimeLimits",
  "runtimeCompression", "knowledgeLibrary", "knowledgeSources", "knowledgeResearch", "knowledgeRelationships", "knowledgeGraph",
  "corpIdentity", "scenarios", "connectors", "databases", "toolCatalog", "workspaceKnowledge", "knowledgePackages",
  "knowledgeBindings", "knowledgeChanges", "knowledgeHandbook", "knowledgeMemory", "knowledgeEpisodes", "knowledge", "agents",
  "effectiveSetup", "workflowList", "workflowChecks", "workflowDesigner", "promptCatalog",
  "instructions", "schedulers", "tasks", "webhooks", "channels", "mcp", "tts", "skills",
  "usage", "observabilityOverview", "operationsCosts", "operationsLive", "observabilityHealth", "observabilityAudit",
  "observabilityDecisions", "approvalDetail", "observabilityRuns", "branding", "personality", "callAgents"];

function loadPanelContent() {
  const pages = new Map();
  const page = (name) => {
    if (!pages.has(name)) {
      pages.set(name, (props) => createElement("page", { name, props: JSON.stringify(props, (key, value) =>
        (typeof value === "function" ? "fn" : key === "children" ? undefined : value)) }, props.children));
    }
    return pages.get(name);
  };
  const lazyPages = new Proxy({}, {
    get: (_target, name) => (name === "__esModule" ? true : page(String(name))),
  });
  const load = loader({ window: windowStub() }, { "/adminPanelLazyPages": lazyPages });
  return load("admin/components/AdminPanelContent.tsx").AdminPanelContent;
}

test("the admin panel switch renders the same page with the same props for every tab", () => {
  const AdminPanelContent = loadPanelContent();
  const ctx = (name) => ({ name });
  const base = {
    loadingTab: false, tabError: null, projects: [{ id: "ws-1", name: "Claims" }], readJson: async () => ({}), isAdmin: true,
    currentUserId: "u-1", brandingEnabled: true,
    ...Object.fromEntries(["users", "projects", "providers", "runtimes", "scenarios", "connectors", "toolCatalog", "knowledge",
      "agents", "schedulers", "tasks", "webhooks", "channels", "mcp", "tts", "skills", "branding"].map((name) => [`${name}TabCtx`, ctx(name)])),
  };
  const lines = TABS.map((tab) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(AdminPanelContent, { ...base, tab })); });
    const line = `${tab}: ${JSON.stringify(view.toJSON())}`;
    act(() => view.unmount());
    return line;
  });
  assert.equal(lines.length, 77);
  assert.ok(lines.every((line) => !line.endsWith(": null")), "every tab renders a page");
  assert.match(lines.find((line) => line.startsWith("classificationPolicy:")), /"name":"AdminClassificationPolicy","props":"\{\\"isAdmin\\":true\}"/);
  assert.match(lines.find((line) => line.startsWith("identityGroups:")), /\\"section\\":\\"groups\\"/);
  const digest = crypto.createHash("sha256").update(lines.join("\n")).digest("hex");
  assert.equal(digest, "173145295194e04845b0390aafb424c5c8cdf6fb26f6c04c74fb1b25d169d2ee");

  const render = (props) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(AdminPanelContent, { ...base, ...props })); });
    const json = view.toJSON();
    act(() => view.unmount());
    return json;
  };
  assert.equal(render({ tab: "nothing-here" }), null);
  for (const removed of ["approvals", "clarifications", "policyDecisions"]) assert.equal(render({ tab: removed }), null);
  assert.match(JSON.stringify(render({ tab: "branding", brandingEnabled: false })), /"data-testid":"branding-disabled".*Branding is disabled on this platform\./);
  assert.match(JSON.stringify(render({ tab: "users", loadingTab: true })), /Loading this page/);
  const failed = render({ tab: "users", tabError: "Boom", onRetry: () => {} });
  assert.equal(failed.props["data-testid"], "admin-tab-error");
  assert.match(JSON.stringify(failed), /Boom.*Retry/);
});
