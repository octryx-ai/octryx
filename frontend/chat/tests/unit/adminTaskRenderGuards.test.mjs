// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminTaskRenderGuards.test.mjs
//
// Render guards for admin components that had no rendering test: the Action step form, the guided
// Action fields, the scenario modal and the call agents tab keep their key labels, fields and buttons.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { act, byTestId, load, render, server, text, tick } from "./settingsRenderHarness.mjs";

const noop = () => {};
const labels = (view) => view.root.findAll((node) => node.type === "label" || node.type === "legend").map(text);
const buttons = (view) => view.root.findAll((node) => node.type === "button").map((node) => text(node).trim());

function mount(relative, exportName, props) {
  const module = load(relative, { fetch: server(() => ({ status: 200, body: {} })).fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(module[exportName], props)); });
  return view;
}

test("the Action step form shows its fields, the connector action and its buttons", () => {
  const view = mount("admin/components/AdminTaskStepForm.tsx", "AdminTaskStepForm", {
    taskId: "t1", editingStep: { id: "s1", name: "Fetch tickets" }, stepFormName: "Fetch tickets", setStepFormName: noop,
    stepFormType: "connector_fetch", setStepFormType: noop, stepFormConnector: "jira", setStepFormConnector: noop,
    stepFormConnectorAction: "search", setStepFormConnectorAction: noop, stepFormInstructions: "", setStepFormInstructions: noop,
    stepFormAgentId: "", setStepFormAgentId: noop, panelAgents: [], stepFormContextFields: "", setStepFormContextFields: noop,
    stepFormConnectorParams: "", setStepFormConnectorParams: noop, stepFormMaxFix: 2, setStepFormMaxFix: noop,
    stepFormTimeout: 60, setStepFormTimeout: noop, stepFormError: "Bad step", stepFormLoading: false,
    onSubmitStep: async () => {}, onCancel: noop,
  });
  const labelText = labels(view).join("|");
  for (const label of ["Step name", "Type", "Action", "Instructions"]) assert.match(labelText, new RegExp(label));
  assert.doesNotMatch(labelText, /Runtime|Tag/);
  assert.deepEqual(buttons(view).slice(-2), ["Save Step", "Cancel"]);
  assert.match(text(view.root.findByProps({ className: "step-form__title" })), /Fetch tickets/);
  assert.equal(view.root.findByProps({ className: "admin-panel__form-error" }).children[0], "Bad step");
  assert.equal(view.root.findAll((node) => node.type === "option").length >= 14, true);
});

const guidedProps = (overrides = {}) => ({
  isNew: true, workspaces: [{ id: "ws-1", name: "Ops" }], workspaceId: "ws-1", workspaceLabel: "Ops", onWorkspace: noop,
  agents: [{ id: "a1", name: "Triage", projectId: null }], agentId: "a1", agent: { id: "a1", name: "Triage" },
  agentAvailable: true, onAgent: noop, modeLabel: "Plan", execution: { text: "Runs the draft.", runnable: true, retry: true },
  onRetryExecution: noop, instructionNote: "Checked at run time.",
  config: { error: null, prompt: "", capability: "read_only", capabilityInvalid: null, promptInvalid: false, reserved: [] },
  onPrompt: noop, onCapability: noop, bindingText: "Runs the agent directly.", offerConversion: true, convertBinding: false,
  onConvertBinding: noop, ...overrides,
});

test("the guided Action fields show workspace, agent, execution, binding, capability and instruction", () => {
  const view = mount("admin/components/automation/ActionGuidedFields.tsx", "ActionGuidedFields", guidedProps());
  const byTestText = (id) => text(byTestId(view, id)[0]);
  assert.match(byTestText("action-guided-execution"), /Runs the draft\. Retry/);
  assert.match(byTestText("action-guided-mode"), /Run mode: Plan/);
  assert.equal(byTestText("action-guided-binding"), "Runs the agent directly.");
  assert.equal(byTestText("action-guided-instruction-note"), "Checked at run time.");
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props.type === "radio").length, 3);
  assert.equal(view.root.findAll((node) => node.props.id === "action-guided-binding-convert").length, 1);
  const edit = mount("admin/components/automation/ActionGuidedFields.tsx", "ActionGuidedFields",
    guidedProps({ isNew: false, agents: [], agent: null, agentId: "", config: { ...guidedProps().config, error: "Bad JSON." } }));
  assert.match(text(edit.root), /\(an action keeps its workspace\)/);
  assert.match(text(edit.root), /No active agent is available in this workspace\. Open agents/);
  assert.match(text(edit.root), /Bad JSON\. Fix it under Advanced to use these fields\./);
});

test("the scenario modal renders its sections and the create button, and nothing when closed", () => {
  const props = {
    show: true, editingScenarioId: null, projects: [{ id: "p1", name: "Ops" }], scenarioName: "Route", setScenarioName: noop,
    scenarioProjectId: "p1", setScenarioProjectId: noop, scenarioPriority: 1, setScenarioPriority: noop, scenarioActive: true,
    setScenarioActive: noop, scenarioDescription: "", setScenarioDescription: noop,
    scenarioMatchConfig: JSON.stringify({ route_reasons: ["incident"], required_domains: [] }), setScenarioMatchConfig: noop,
    scenarioPlannerConfig: "{}", setScenarioPlannerConfig: noop, scenarioExecutionConfig: "{}", setScenarioExecutionConfig: noop,
    scenarioFormError: "Name taken", scenarioFormLoading: false, onSaveScenario: noop, onClose: noop,
  };
  const view = mount("admin/components/AdminScenarioFormModal.tsx", "AdminScenarioFormModal", props);
  assert.equal(text(view.root.findByProps({ className: "admin-panel__title" })), "New Scenario");
  assert.deepEqual(buttons(view).slice(-2), ["Create Scenario", "Cancel"]);
  assert.match(text(view.root), /Name taken/);
  assert.equal(view.root.findAllByType("form").length, 1);
  const closed = mount("admin/components/AdminScenarioFormModal.tsx", "AdminScenarioFormModal", { ...props, show: false });
  assert.equal(closed.toJSON(), null);
});

test("the call agents tab lists a Workspace's call agents and opens the side panel", async () => {
  const srv = server((call) => {
    if (call.url.includes("/configs?")) return { status: 200, body: { configs: [{ id: "c1", name: "Hotline", llm_model: "m1", channel_id: "ch1" }] } };
    if (call.url.includes("/channels?")) return { status: 200, body: { channels: [{ id: "ch1", name: "Phone", plugin_id: "x" }] } };
    return { status: 200, body: { models: [], count: 0 } };
  });
  const view = await render("admin/components/AdminCallAgentsTab.tsx", "AdminCallAgentsTab", srv, { projects: [{ id: "p1", name: "Ops" }] });
  assert.equal(byTestId(view, "call-agents-select-workspace").length > 0, true);
  const select = view.root.find((node) => node.type === "select");
  await act(async () => { select.props.onChange({ target: { value: "p1" } }); });
  await tick();
  assert.match(text(view.root), /Call agents \(1\)/);
  assert.match(text(byTestId(view, "call-agents-table")[0]), /Hotline.*m1.*Phone/);
  await act(async () => { byTestId(view, "call-agent-new")[0].props.onClick(); });
  assert.deepEqual(buttons(view).filter((label) => label === "Save" || label === "Cancel"), ["Cancel", "Save"]);
});
