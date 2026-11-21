// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/boundActionDetails.test.mjs
//
// Bound Action details, rendered with the real steps section and runs panel. An Action
// explicitly bound to its agent (dispatch_binding "agent_definition") keeps its Action dependencies
// but offers no step creation or editing (the server refuses enabled Action steps on it); it points to
// the canonical agent page instead and lists saved steps read-only. Null, missing or unknown bindings
// keep the step editor unchanged. The queued note assumes no dispatch path; known per-row waiting
// reasons stay.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    // Exact file-name case, so a wrong-case path also fails on case-insensitive hosts.
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(ADMIN, relative));
}
const { AdminTaskStepsSection } = load("components/AdminTaskStepsSection.tsx");
const { AdminTaskRunsPanel } = load("components/AdminTaskRunsPanel.tsx");

const task = (overrides = {}) => ({
  id: "task-1", name: "Digest", description: "", task_type: "agent_run", agent_type: "diagnosis", is_active: true,
  run_count: 1, running_count: 0, last_run_status: null, last_run_at: null, step_count: 0, project_id: "ws-1",
  config: { agent_definition_id: "agent-1" }, ...overrides,
});
const step = (id, position, is_enabled) => ({
  id, task_id: "task-1", position, name: `Step ${id}`, step_type: "analysis", connector: null, connector_action: null,
  connector_params: {}, instructions: "Old step instructions", runtime_selector: {}, context_fields: [],
  max_fix_attempts: 1, agent_timeout_seconds: 60, is_enabled,
});

function renderSteps(taskRow, { steps = [], staleForm = false } = {}) {
  const calls = [];
  const record = (name) => (...args) => { calls.push([name, ...args]); return Promise.resolve(); };
  const props = {
    isExpanded: true, task: taskRow,
    taskDependencies: { "task-1": { dependencies: [], dependents: [], available_tasks: [{ id: "task-2", name: "Upstream" }] } },
    onDeleteTaskDependency: record("deleteDependency"), taskDependencyTarget: {}, setTaskDependencyTarget: () => {},
    taskDependencyCondition: {}, setTaskDependencyCondition: () => {}, onAddTaskDependency: record("addDependency"),
    taskSteps: { "task-1": steps }, onExpandSteps: record("expandSteps"), onOpenStepForm: record("openStepForm"),
    // A step form left open for this Action (e.g. opened before it was bound) must not render.
    showStepForm: staleForm ? "task-1" : null, setShowStepForm: () => {}, editingStep: staleForm ? steps[0] ?? null : null,
    setEditingStep: () => {}, panelAgents: [], onSaveStep: record("saveStep"), onMoveStep: record("moveStep"),
    onDeleteStep: record("deleteStep"), stepFormError: null, stepFormLoading: false,
    stepFormMaxFix: 1, setStepFormMaxFix: () => {}, stepFormTimeout: 60, setStepFormTimeout: () => {},
  };
  for (const name of ["Name", "Type", "Connector", "ConnectorAction", "Instructions", "RuntimeMode", "RuntimeTag",
    "AgentId", "ContextFields", "ConnectorParams"]) {
    props[`stepForm${name}`] = "";
    props[`setStepForm${name}`] = () => {};
  }
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminTaskStepsSection, props)); });
  const buttons = (label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label);
  return {
    view, calls, buttons, all: text(view.root),
    dialog: view.root.findAll((node) => node.props.role === "dialog").length,
  };
}

test("a bound Action keeps its dependencies but offers no step editing, even for a stale open form", () => {
  const ui = renderSteps(task({ dispatch_binding: "agent_definition" }), { steps: [step("s2", 2, false)], staleForm: true });
  assert.ok(ui.all.includes("Action dependencies"), "the dependency section stays, under an understandable name");
  assert.ok(!ui.all.includes("DAG View"));
  assert.equal(ui.dialog, 0, "no step editor, even when one was left open");
  for (const label of ["+ Add Step", "✏", "Del", "↑", "↓"]) assert.equal(ui.buttons(label).length, 0, label);
  assert.ok(ui.all.includes("Its instructions and steps belong to that agent and are edited on the agent's page."));
  const link = ui.view.root.find((node) => node.type === "a" && text(node) === "Open agent ↗");
  assert.deepEqual([link.props.href, link.props.target, link.props.rel],
    ["/chat?area=workflows&tab=agents&agent_id=agent-1", "_blank", "noopener noreferrer"], "the canonical agent page");
  // The saved disabled step stays visible, read-only, and is not presented as having run.
  const saved = ui.view.root.find((node) => node.props["data-testid"] === "bound-action-saved-steps");
  assert.ok(text(saved).includes("Step s2") && text(saved).includes("disabled"));
  assert.ok(!/No steps yet|succeeded|completed/.test(ui.all));
  // Dependencies remain operable; no step callback can be reached from the bound view.
  act(() => { ui.buttons("+ Add dependency")[0].props.onClick(); });
  assert.deepEqual(ui.calls.map(([name]) => name), ["addDependency"], "only the dependency callback is reachable");
});

test("a bound Action without a reported agent says so instead of linking anywhere", () => {
  const ui = renderSteps(task({ dispatch_binding: "agent_definition", config: {} }));
  assert.equal(ui.view.root.findAll((node) => node.type === "a").length, 0);
  assert.ok(ui.all.includes("This server does not report the selected agent."));
});

test("task_definition, missing or unknown bindings keep the step editor exactly", () => {
  for (const binding of [{ dispatch_binding: "task_definition" }, {}, { dispatch_binding: "something_else" }]) {
    const label = JSON.stringify(binding);
    const ui = renderSteps(task(binding), { steps: [step("s1", 1, true)] });
    assert.equal(ui.view.root.findAll((node) => node.props["data-testid"] === "bound-action-agent-steps").length, 0, label);
    assert.ok(ui.all.includes("Action dependencies") && ui.all.includes("Steps (1)"), label);
    act(() => { ui.buttons("+ Add Step")[0].props.onClick(); });
    act(() => { ui.buttons("✏")[0].props.onClick(); });
    assert.deepEqual(ui.calls.map(([name]) => name), ["expandSteps", "openStepForm", "openStepForm"], label);
    assert.equal(renderSteps(task(binding), { steps: [step("s1", 1, true)], staleForm: true }).dialog, 1, `${label}: the open form still renders`);
  }
});

function renderRuns(runs) {
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminTaskRunsPanel, {
      isExpanded: true, runCount: runs.length, taskId: "task-1", runsLoading: null, runsError: null, runs,
      expandedRun: null, setExpandedRun: () => {}, statusColor: {}, setTaskRuns: () => {},
      loadTaskRuns: async () => {}, cancellingRun: null, handleCancelRun: async () => {},
    }));
  });
  return {
    all: text(view.root),
    note: view.root.findAll((node) => node.props["data-testid"] === "task-runs-queued-note").map(text)[0] ?? null,
  };
}
const queuedRun = (id, reason) => ({
  id: `${id}-0000000000`, task_id: "task-1", session_id: null, status: "queued", started_by: "u", started_at: null,
  completed_at: null, error: null, duration_seconds: null, steps_log: [], queue_priority: 5, queue_status: "pending",
  queue_required_domain: "any", queued_at: "2026-10-04T10:00:00", estimated_wait_seconds: null, queue_wait_reason: reason,
});

test("the queued note assumes no worker; a known per-row reason is still explained", () => {
  const unknown = renderRuns([queuedRun("a", null)]);
  assert.doesNotMatch(unknown.note, /worker/i, "no dispatch path is assumed for an unexplained queued run");
  assert.ok(unknown.note.includes("this list does not report why it is still waiting."));
  assert.ok(unknown.note.includes("Use Refresh to check again."));

  const known = renderRuns([queuedRun("b", "no_available_workers")]);
  assert.doesNotMatch(known.note, /worker/i);
  assert.ok(known.note.includes("each row says why it is still waiting."));
  assert.ok(known.all.includes("no worker is available to start it"), "the genuine per-row reason stays");
});
