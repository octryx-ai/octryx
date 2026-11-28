// Render guards for admin parts split into smaller functions: Default & fallback with its order and task tabs, the
// policy impact pane, the structured graph panel, the Workspace agents and diagnostics card, and the settings drawer
// render the same structure and make the same calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

const model = (key, patch = {}) => ({ catalog_key: key, display_name: key.toUpperCase(), provider: "bedrock", enabled: true,
  cleared_up_to: "internal", capabilities: { tools: true }, ...patch });
const selection = { order: [model("a"), model("b")], fallback: "next", models: [model("a"), model("b"), model("c"), model("d", { enabled: false })],
  tasks: [{ key: "title", label: "Titles", model_key: "b", workspace_overrides: 2 }, { key: "sum", label: "Summaries", workspace_overrides: 0 }] };

test("Default & fallback edits the platform order and the task models and saves each", async () => {
  const saved = [], opened = [];
  const { AdminDefaultAndFallback } = loadStubbed("admin/components/modelSelection/AdminDefaultAndFallback.tsx", ["/LoadingState",
    "/SegmentedTabs", "/EngineCards", "/LocalModelsCard", "./ExplainTurn"], {}, {
    "./modelSelectionApi": { loadSelection: async () => selection, saveOrder: async (...args) => { saved.push(["order", ...args]); return selection; },
      saveTasks: async (tasks) => { saved.push(["tasks", tasks]); throw new Error("no"); } },
    "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } });
  const view = await createAsync(createElement(AdminDefaultAndFallback));
  includesAll(text(view.root), ["A", " · platform default", "bedrock · cleared up to", "B", "Add to the order", "Choose an enabled model",
    "C · bedrock", "When a model fails", "Try the next allowed model", "Stop with an error", "Save order and fallback"]);
  assert.deepEqual(buttons(view).slice(0, 3), ["↑", "↓", "✕"]);
  assert.equal(byTestId(view, "order-save")[0].props.disabled, true);
  assert.equal(hostCount(view), 49);
  act(() => byTestId(view, "order-add-select")[0].props.onChange({ target: { value: "c" } }));
  act(() => byTestId(view, "order-add")[0].props.onClick());
  act(() => byTestId(view, "fallback-stop")[0].props.onChange());
  act(() => all(view, "button").find((node) => node.props["aria-label"] === "Move B down").props.onClick());
  act(() => all(view, "button").find((node) => node.props["aria-label"] === "Remove A from the order").props.onClick());
  await act(async () => byTestId(view, "order-save")[0].props.onClick());
  assert.deepEqual(plain(saved[0]), ["order", ["c", "b"], "stop"]);
  includesAll(text(view.root), ["Saved: platform order and fallback (only these two settings)."]);
  act(() => stubs(view, "SegmentedTabs")[0].props.onChange("tasks"));
  includesAll(text(view.root), ["Task", "Titles", "2 Workspaces", "Summaries", "None", "Platform default (A)", "Save task models",
    "Open policy lists"]);
  assert.equal(byTestId(view, "task-model-title")[0].props.value, "b");
  assert.equal(hostCount(view), 31);
  act(() => byTestId(view, "task-model-sum")[0].props.onChange({ target: { value: "a" } }));
  await act(async () => byTestId(view, "tasks-save")[0].props.onClick());
  assert.deepEqual(plain(saved[1]), ["tasks", { title: "b", sum: "a" }]);
  assert.equal(all(view, "p").filter((node) => node.props.role === "alert").length, 1);
  act(() => button(view, "Open policy lists").props.onClick());
  assert.deepEqual(opened, ["runtimePolicyLists"]);
  for (const [tab, stub] of [["engine", "PlatformEngineCard"], ["explain", "ExplainTurn"]]) {
    act(() => stubs(view, "SegmentedTabs")[0].props.onChange(tab));
    assert.equal(stubs(view, stub).length, 1);
  }
});

test("the policy impact pane runs the examples, marks each and saves them as test cases", async () => {
  const saved = [];
  const impact = { workspace: { name: "Harbor" }, notes: ["n1"], policy_source: "draft", cases: null, examples: [
    { name: "Delete prod", kind: "block", request: {}, answer: { decision: "deny", determining: ["p1", "p2"], as_expected: true } },
    { name: "Read docs", kind: "control", request: {}, answer: { decision: "deny", determining: [], as_expected: false } },
    { name: "Broken", kind: "block", request: {}, answer: { error: "x", determining: [], as_expected: true } }] };
  const load = (api) => loadStubbed("admin/components/policyEngine/PolicyImpact.tsx", ["./PolicyRef", "./PolicyTestReport"], {},
    { "./policyEngineApi": { generateExamples: async () => impact, saveTestCase: async (body) => { saved.push(body); }, ...api } }).PolicyImpact;
  const PolicyImpact = load({});
  const view = await createAsync(createElement(PolicyImpact, { model: {}, originalId: null, policyName: "P", onOpenBench() {} }));
  includesAll(text(view.root), ["What would this block?", "Test bench · draft", "Asked for the Workspace Harbor.", "n1", "Blocked", "Delete prod",
    " · by , ", "Read docs — control", " · not as intended: this policy blocks it", "Error", "Broken", "Save examples as test cases",
    "Open in test bench", "Ask again", "Saved test cases with this policy"]);
  assert.equal(stubs(view, "PolicyRef").length, 2);
  assert.equal(byTestId(view, "policy-impact-save")[2].props.disabled, true);
  assert.equal(hostCount(view), 31);
  await act(async () => byTestId(view, "policy-impact-save-all")[0].props.onClick());
  assert.deepEqual(plain(saved.map((item) => item.expected)), ["deny", "allow"]);
  includesAll(text(view.root), ["2 examples saved as test cases."]);
  await act(async () => byTestId(view, "policy-impact-save")[0].props.onClick());
  includesAll(text(view.root), ["Saved as a test case."]);
  const manual = create(createElement(load({ generateExamples: async () => { throw new Error("refused"); } }),
    { model: {}, originalId: "o", policyName: "P", auto: false }));
  assert.deepEqual(buttons(manual), ["Run examples"]);
  await act(async () => byTestId(manual, "policy-impact-run")[0].props.onClick());
  assert.equal(byTestId(manual, "policy-impact-message")[0].props.role, "alert");
});

test("the structured graph panel builds chosen layers, filters the report and shows it", async () => {
  const calls = [];
  const report = { state: "ok", counts: {}, undocumented_in_known_section: [] };
  const api = { status: async (id) => { calls.push(["status", id]); return { layers: { manual: { revisions: 1, nodes: 2, edges: 3 } }, builds: [],
    runner: { status: "success", updated_at: "now" } }; },
  report: async (id, filters) => { calls.push(["report", filters]); return report; },
  build: async (id, layers) => { calls.push(["build", layers]); } };
  const { StructuredGraphPanel } = loadStubbed("admin/components/workspaceKnowledge/StructuredGraphPanel.tsx", ["./HandbookReportView"], {},
    { "./structuredGraphApi": { STRUCTURED_LAYERS: ["manual", "configuration", "operations"], structuredGraphApi: api } });
  const view = await createAsync(createElement(StructuredGraphPanel, { workspaceId: "w1" }));
  includesAll(text(view.root), ["Structured graph", "Rule-based, cited", "1 sources · 2 nodes · 3 relationships", "not built",
    "No structured graph has been built", "The build runner last reported at now.", "Layers to build", "Build structured graph", "Refresh",
    "Handbook vs. reality", "Filter"]);
  assert.equal(stubs(view, "HandbookReportView").length, 1);
  assert.equal(all(view, "input").length, 6);
  assert.equal(hostCount(view), 28);
  act(() => all(view, "input")[1].props.onChange());
  act(() => all(view, "input")[3].props.onChange({ target: { value: "Lock" } }));
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  await act(async () => button(view, "Build structured graph").props.onClick());
  await tick();
  assert.deepEqual(plain(calls.filter((call) => call[0] !== "status")), [["report", { parameter: "", file: "", section: "" }],
    ["report", { parameter: "Lock", file: "", section: "" }], ["build", ["manual", "operations"]], ["report", { parameter: "Lock", file: "", section: "" }]]);
  const failed = await createAsync(createElement(loadStubbed("admin/components/workspaceKnowledge/StructuredGraphPanel.tsx", ["./HandbookReportView"],
    {}, { "./structuredGraphApi": { STRUCTURED_LAYERS: ["manual"], structuredGraphApi: { ...api, status: async () => { throw new Error("Gone"); },
      report: async () => ({ state: "not_built" }) } } }).StructuredGraphPanel, { workspaceId: "w1" }));
  includesAll(text(failed.root), ["Gone"]);
});

test("the Workspace agents and diagnostics card shows the assignments or the warnings and reloads", () => {
  const reloads = [];
  const state = { payload: { assignment_controls: { agent_assignment_mode: "selected_only", runtime_assignment_mode: "all" },
    diagnostics: { warnings: ["w"] }, bindings: [] }, loading: false, error: null, reload: () => reloads.push(1),
  bindingsByKind: [["agent", [{ id: "b1" }, { id: "b2" }]]], savingBindingId: "b2", savingAssignmentControls: false,
  updateBinding() {}, updateAssignmentControls() {} };
  let current = state;
  const { AdminWorkspaceCompositionSection } = loadStubbed("admin/components/projectsTab/AdminWorkspaceCompositionSection.tsx",
    ["/WorkspaceCapabilityBindingCard", "/WorkspaceDiagnosticsPanel", "/WorkspaceAssignmentControlsPanel"], {}, {
      "/useAdminWorkspaceComposition": { useAdminWorkspaceComposition: () => current },
      "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab() {} }) } });
  const ctx = { configuringProjectQuality: { id: "p1" }, readJson() {} };
  const agents = create(createElement(AdminWorkspaceCompositionSection, { ctx, view: "agents" }));
  includesAll(text(agents.root), ["Agents", "Refresh", "Whether this Workspace can use every installed agent",
    "Only the agents enabled below are available in this Workspace.", "Open agents"]);
  assert.deepEqual(stubs(agents, "WorkspaceCapabilityBindingCard").map((node) => node.props.isSaving), [false, true]);
  assert.equal(stubs(agents, "WorkspaceAssignmentControlsPanel")[0].props.view, "agents");
  assert.equal(hostCount(agents), 11);
  act(() => button(agents, "Refresh").props.onClick());
  assert.equal(reloads.length, 1);
  current = { ...state, bindingsByKind: [], payload: { ...state.payload, assignment_controls: { agent_assignment_mode: "all" } } };
  const none = create(createElement(AdminWorkspaceCompositionSection, { ctx, view: "agents" }));
  includesAll(text(none.root), ["Every active agent of the catalog is available", "No agent is pinned to this Workspace."]);
  current = state;
  const diagnostics = create(createElement(AdminWorkspaceCompositionSection, { ctx, view: "diagnostics", onOpenSection() {} }));
  includesAll(text(diagnostics.root), ["Diagnostics", "Configuration problems in this Workspace"]);
  assert.equal(stubs(diagnostics, "WorkspaceDiagnosticsPanel")[0].props.runtimeAssignmentMode, "all");
  current = { ...state, payload: null, loading: true, error: "Bad" };
  const loading = create(createElement(AdminWorkspaceCompositionSection, { ctx, view: "agents" }));
  includesAll(text(loading.root), ["Refreshing…", "Bad", "Loading…"]);
});

test("the settings drawer is a labelled dialog that closes on Escape, the backdrop and its close button", () => {
  const listeners = {};
  const focused = [];
  const document = { activeElement: { focus: () => focused.push("back") }, addEventListener: (name, fn) => { listeners[name] = fn; },
    removeEventListener: (name) => { delete listeners[name]; } };
  const { SettingsDrawer } = loadStubbed("admin/components/projectsTab/SettingsDrawer.tsx", [], { document });
  const closed = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(SettingsDrawer, { eyebrow: "Edit", title: "Harbor", size: "detail", onClose: () => closed.push(1),
    footer: createElement("span", null, "Foot"), headerActions: createElement("b", null, "Act") }, createElement("p", null, "Body")), {
    createNodeMock: () => ({ contains: () => false, focus: () => focused.push("dialog") }) }); });
  includesAll(text(view.root), ["Edit", "Harbor", "Act", "Body", "Foot"]);
  const dialog = view.root.findAll((node) => node.props.role === "dialog")[0];
  assert.equal(dialog.props.className, "settings-drawer settings-drawer--detail");
  assert.equal(hostCount(view), 15);
  const prevented = [];
  act(() => listeners.keydown({ key: "Escape", defaultPrevented: false, preventDefault: () => prevented.push(1) }));
  act(() => listeners.keydown({ key: "Escape", defaultPrevented: true, preventDefault() {} }));
  const backdrop = all(view, "div")[0];
  act(() => backdrop.props.onMouseDown({ target: 1, currentTarget: 1 }));
  act(() => backdrop.props.onMouseDown({ target: 1, currentTarget: 2 }));
  act(() => button(view, "").props.onClick());
  assert.deepEqual([closed.length, prevented.length], [3, 1]);
  act(() => view.unmount());
  assert.equal(listeners.keydown, undefined);
  assert.deepEqual(focused, ["dialog", "back"]);
});
