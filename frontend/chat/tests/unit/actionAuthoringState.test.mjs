// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionAuthoringState.test.mjs
//
// The Action header, form and card with the real useAdminTaskState and useAdminTaskCoreActions
// (readJson is the only stub). Edit → Cancel → New, New while editing and New → Cancel → New all start
// from the canonical clean form; an edit of an Action the guided form does not represent shows its saved
// values and why, and saving omits its type and run mode (both kept) and sends no schedule or activation. A paused
// Action card stays readable: no inactive fade, an explicit Paused badge, its controls in place.
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

const MODES = [
  { id: "1", key: "diagnosis", name: "Diagnosis", is_active: true, capability_type: "diagnosis" },
  { id: "2", key: "change", name: "Change", is_active: true, capability_type: "change" },
];
const requests = [];
async function stubRead(url, init = {}) {
  const body = init.body ? JSON.parse(init.body) : null;
  requests.push({ url, method: init.method || "GET", body });
  if (url.includes("agent-modes")) return MODES;
  return { ...SAVED, ...body };
}

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, setTimeout, clearTimeout, AbortController, Date,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(ADMIN, relative));
}

const loadModule = makeLoader({ "/utils/adminPanelHelpers": { readJson: stubRead } });
const { AdminNavigationContext } = loadModule("adminNavigation.ts");
const { AdminTasksTabHeader } = loadModule("components/AdminTasksTabHeader.tsx");
const { AdminTaskForm } = loadModule("components/AdminTaskForm.tsx");
const { AdminTaskCard } = loadModule("components/AdminTaskCard.tsx");
const { useAdminTaskState } = loadModule("hooks/useAdminTaskState.ts");
const { useAdminTaskCoreActions } = loadModule("hooks/useAdminTaskCoreActions.ts");

// The Jira sync Action from the browser evidence: a saved type the form does not offer.
const SAVED = {
  id: "task-jira", name: "Jira sync", description: "Keeps SHOP tickets in sync", task_type: "secure_work_jira_sync",
  agent_type: "change", schedule: "0 9 * * 7", is_active: false, running_count: 0, queued_count: 0,
  config: { jira_project: "ORDERS", max_iterations: 12, agent_definition_id: "agent-1" },
};
const CLEAN = { name: "", desc: "", config: "{}", maxIterations: 32, agent: "" };

function mount() {
  requests.length = 0;
  const handle = {};
  function Harness() {
    const state = useAdminTaskState();
    const actions = useAdminTaskCoreActions({
      args: { ...state, readJson: stubRead, panelAgents: [{ id: "agent-1", name: "Jira agent" }] },
      loadTaskSteps: async () => {},
    });
    Object.assign(handle, { state, actions });
    const ctx = { ...state, onOpenTaskForm: actions.handleOpenTaskForm, onCloseTaskForm: actions.closeTaskForm };
    return createElement("div", null,
      createElement(AdminTasksTabHeader, { ctx }),
      createElement(AdminTaskForm, {
        ...state, panelAgents: [{ id: "agent-1", name: "Jira agent" }], projects: [{ id: "ws-1", name: "Alpha" }],
        onSaveTask: actions.handleSaveTask, onCloseTaskForm: actions.closeTaskForm,
      }));
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } }, createElement(Harness)));
  });
  const button = (label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
  const forms = () => view.root.findAllByType("form");
  const select = (id) => view.root.find((node) => node.type === "select" && node.props.id === id);
  return {
    handle, view, button, forms,
    values: () => {
      const s = handle.state;
      return { name: s.taskFormName, desc: s.taskFormDesc, config: s.taskFormConfig, maxIterations: s.taskFormMaxIterations,
        agent: s.taskFormAgentDefId };
    },
    shown: () => {
      const inputs = forms()[0].findAllByType("input");
      return { name: inputs[0].props.value, desc: inputs[1].props.value };
    },
    title: () => text(view.root.find((node) => node.type === "h2" && node.props.className === "ds-panel__title")),
    select,
    edit: () => act(() => handle.actions.handleOpenTaskForm(SAVED)),
    // The page's New action (rendered in place without the admin header slot) or the side panel's Cancel.
    click: (label) => act(() => view.root.find((node) => node.type === "button" && text(node).trim() === label).props.onClick()),
    closeX: () => act(() => view.root.find((node) => node.type === "button" && node.props["data-testid"] === "action-panel-close").props.onClick()),
    type: (setter, value) => act(() => handle.state[setter](value)),
  };
}

test("an edit of an Action the guided form does not represent shows its saved values and why", () => {
  const ui = mount();
  ui.edit();
  assert.equal(ui.title(), "Edit Jira sync");
  assert.deepEqual(ui.values(), {
    name: "Jira sync", desc: "Keeps SHOP tickets in sync",
    config: JSON.stringify({ jira_project: "ORDERS" }, null, 2), maxIterations: 12, agent: "agent-1",
  });
  assert.deepEqual(ui.shown(), { name: "Jira sync", desc: "Keeps SHOP tickets in sync" });
  const note = ui.forms()[0].find((node) => String(node.props.className || "").startsWith("action-guided__unguided"));
  assert.equal(text(note), 'This action has the type "secure_work_jira_sync", which the guided form does not edit.');
  assert.equal(ui.forms()[0].findAllByType("select").length, 0, "no type, run mode or agent choice");
});

test("Edit → Cancel → New action starts from the clean form", () => {
  const ui = mount();
  ui.edit();
  ui.closeX();
  assert.equal(ui.forms().length, 0, "cancel closes");
  ui.click("New action");
  assert.equal(ui.title(), "New action");
  assert.equal(ui.handle.state.editingTask, null);
  assert.deepEqual(ui.values(), CLEAN);
  assert.deepEqual(ui.shown(), { name: "", desc: "" }, "a new Action is the guided agent run");
  assert.equal(ui.select("action-guided-workspace").props.value, "", "no preselected workspace");
  assert.equal(ui.select("action-guided-agent").props.disabled, true);
});

test("New action while an edit is open replaces it with the clean form", () => {
  const ui = mount();
  ui.edit();
  ui.click("New action");
  assert.equal(ui.title(), "New action");
  assert.deepEqual(ui.values(), CLEAN);
});

test("New → typing → panel Cancel → New starts clean again, and cancelling writes nothing", () => {
  const ui = mount();
  ui.click("New action");
  ui.type("setTaskFormName", "Half-typed");
  ui.type("setTaskFormConfig", '{"leftover": true}');
  ui.click("Cancel");
  assert.equal(ui.forms().length, 0);
  ui.click("New action");
  assert.deepEqual(ui.values(), CLEAN);
  assert.equal(requests.filter((request) => request.method !== "GET").length, 0, "no mutation");
});

test("saving an edit of an unguided Action keeps its type and run mode and sends no schedule or activation", async () => {
  const ui = mount();
  ui.edit();
  ui.type("setTaskFormDesc", "Renamed description");
  await act(async () => { await ui.handle.actions.handleSaveTask({ preventDefault() {} }); });
  const [put] = requests.filter((request) => request.method === "PUT");
  assert.equal(put.url, "/admin/chat/api/panel/tasks/task-jira");
  assert.equal(put.body.description, "Renamed description");
  assert.deepEqual(["task_type" in put.body, "agent_type" in put.body], [false, false], "the stored type and run mode are kept");
  assert.deepEqual(["schedule" in put.body, "is_active" in put.body], [false, false]);
});

// ---- the card --------------------------------------------------------------------------------

function card(task) {
  const noop = () => {};
  // Collapsed card: only these props are read; steps, runs and dependencies render when expanded.
  const props = {
    task, isExpanded: false, runs: [], triggeringTask: null, agentModeNameByKey: new Map([["change", "Change"]]),
    onExpandTask: noop, onTriggerTask: noop, onOpenTaskForm: noop, setShowTaskForm: noop, onToggleTask: noop, onDeleteTask: noop,
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminTaskCard, props)); });
  const root = view.root.findByType("div");
  const badges = view.root.findAll((node) => String(node.props.className || "").split(" ").includes("task-item__badge")).map(text);
  return { classes: root.props.className.split(/\s+/).filter(Boolean), badges, buttons: view.root.findAllByType("button") };
}

test("a paused Action card is readable: no inactive fade, an explicit Paused badge, controls kept", () => {
  const paused = card(SAVED);
  assert.ok(!paused.classes.includes("task-item--inactive"), "no whole-row opacity fade");
  assert.ok(paused.classes.includes("admin-task--paused"));
  assert.equal(paused.badges[0], "Paused");
  assert.ok(paused.badges.includes("secure_work_jira_sync"), "the saved type is shown as stored");
  const titles = paused.buttons.map((button) => button.props.title);
  // The disabled Execute of a paused Action says why, not "Execute now".
  assert.ok(titles.includes("Edit") && titles.includes("Paused – resume to run"));

  const active = card({ ...SAVED, is_active: true });
  assert.ok(active.buttons.map((button) => button.props.title).includes("Execute now"));
  assert.ok(!active.classes.includes("admin-task--paused"));
  assert.ok(!active.badges.includes("Paused"));
});
