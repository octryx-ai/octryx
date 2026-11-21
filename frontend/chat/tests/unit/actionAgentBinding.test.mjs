// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionAgentBinding.test.mjs
//
// Explicit Action agent binding (backend contract), rendered with the real form,
// useAdminTaskState and useAdminTaskCoreActions; readJson is the only stub. A new guided Action sends
// dispatch_binding "agent_definition"; an existing "task_definition" Action converts only through an explicit
// opt-in; every other save omits the field so the stored value is kept; server refusals are shown as sent. The
// card states the current setting, never a claim about past runs. "task_definition" is described neutrally as
// the existing execution setup: the backend decides how it is routed (worker, deterministic local steps, ...),
// so no worker requirement is claimed.
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

const MODES = [{ id: "1", key: "diagnosis", name: "Diagnosis", is_active: true }];
const WORKSPACES = [{ id: "ws-1", name: "Alpha" }];
const AGENTS = [{
  id: "agent-1", name: "Digest agent", isActive: true, projectId: "", agentType: "diagnosis", goal: "Summarise",
  systemPrompt: "", outputPrompt: "", steps: [],
}];
const DRAFT = { execution: { mode: "draft", published_revision_number: null }, revision: null };

let requests = [];
let writeReply = (body) => Promise.resolve({ id: "saved", ...body });
function stubRead(url, init = {}) {
  const method = init.method || "GET";
  const body = init.body ? JSON.parse(init.body) : null;
  if (url.endsWith("/panel/modes")) return Promise.resolve(MODES);
  if (method !== "GET") {
    requests.push({ url, method, body });
    return writeReply(body);
  }
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, method, body, ...settle });
  return promise;
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
    // Exact file-name case, so a wrong-case path also fails on case-insensitive hosts.
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      // One Error constructor, so `err instanceof Error` holds across modules as in one browser realm.
      module, exports: module.exports, console, setTimeout, clearTimeout, AbortController, URL, URLSearchParams, Date, Error,
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

let mounted = null;
function mount() {
  if (mounted) act(() => mounted.unmount());
  requests = [];
  writeReply = (body) => Promise.resolve({ id: "saved", ...body });
  const handle = {};
  function Harness() {
    const state = useAdminTaskState();
    const actions = useAdminTaskCoreActions({ args: { ...state, readJson: stubRead }, loadTaskSteps: async () => {} });
    Object.assign(handle, { state, actions });
    const ctx = { ...state, onOpenTaskForm: actions.handleOpenTaskForm, onCloseTaskForm: actions.closeTaskForm };
    return createElement("div", null,
      createElement(AdminTasksTabHeader, { ctx }),
      createElement(AdminTaskForm, {
        ...state, panelAgents: AGENTS, projects: WORKSPACES,
        onSaveTask: actions.handleSaveTask, onCloseTaskForm: actions.closeTaskForm,
      }));
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider,
      { value: { openAdminTab: () => {} } }, createElement(Harness)));
  });
  mounted = view;
  const byId = (id) => view.root.findAll((node) => typeof node.type === "string" && node.props.id === id)[0] ?? null;
  const ui = {
    handle, view, byId,
    howItRuns: () => view.root.findAll((node) => node.props["data-testid"] === "action-guided-binding").map(text)[0] ?? null,
    convertBox: () => byId("action-guided-binding-convert"),
    convert: (checked) => act(() => byId("action-guided-binding-convert").props.onChange({ target: { checked } })),
    openNew: () => act(() => view.root.find((node) => node.type === "button" && node.props["data-testid"] === "action-new").props.onClick()),
    edit: (task) => act(() => handle.actions.handleOpenTaskForm(task)),
    close: () => act(() => handle.actions.closeTaskForm()),
    change: (id, value) => act(() => byId(id).props.onChange({ target: { value } })),
    // Answers the newest execution lookup so the guided gate can open.
    runnable: () => act(async () => { requests.filter((r) => r.url.endsWith("/designer-document")).at(-1).resolve(DRAFT); }),
    submit: () => act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); }),
    writes: () => requests.filter((request) => request.method !== "GET"),
    formError: () => view.root.findAll((node) => node.props.className === "admin-panel__form-error").map(text)[0] ?? null,
  };
  return ui;
}

const row = (overrides = {}) => ({
  id: "task-1", name: "Nightly digest", description: "", task_type: "agent_run", agent_type: "diagnosis",
  schedule: null, is_active: true, step_count: 0, project_id: "ws-1", run_count: 3, running_count: 0,
  last_run_status: "success", last_run_at: null, config: { agent_definition_id: "agent-1" }, ...overrides,
});

test("a new guided Action explicitly sends agent_definition and says it runs its agent directly", async () => {
  const ui = mount();
  ui.openNew();
  assert.match(ui.howItRuns(), /^Runs the chosen agent directly/);
  assert.equal(ui.convertBox(), null, "nothing to convert on a new Action");
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "agent-1");
  await ui.runnable();
  act(() => ui.handle.state.setTaskFormName("Digest"));
  await ui.submit();
  const [post] = ui.writes();
  assert.equal(post.method, "POST");
  assert.equal(post.body.dispatch_binding, "agent_definition");
});

test("an Action without an explicit binding is never converted by an ordinary save", async () => {
  const ui = mount();
  ui.edit(row({ dispatch_binding: "task_definition" }));
  assert.equal(ui.howItRuns(),
    "Keeps its existing execution setup: it runs as it is configured today. It is not bound to run its agent directly.");
  assert.doesNotMatch(text(ui.view.root), /worker/i, "no worker requirement is claimed for null");
  assert.equal(ui.convertBox().props.checked, false, "the conversion is offered, unchecked");
  await ui.runnable();
  await ui.submit();
  const [put] = ui.writes();
  assert.equal(put.method, "PUT");
  assert.equal("dispatch_binding" in put.body, false, "omitted, so the stored binding is kept");
});

test("only an explicit opt-in converts it, and the opt-in never carries over", async () => {
  const ui = mount();
  const legacy = row({ dispatch_binding: "task_definition" });
  ui.edit(legacy);
  ui.convert(true);
  ui.close();
  ui.edit(legacy);
  assert.equal(ui.convertBox().props.checked, false, "reopening the same Action starts unchecked");
  ui.convert(true);
  ui.edit(row({ id: "task-2", dispatch_binding: "task_definition" }));
  assert.equal(ui.convertBox().props.checked, false, "switching to another Action starts unchecked");

  ui.edit(legacy);
  ui.convert(true);
  await ui.runnable();
  await ui.submit();
  const [put] = ui.writes();
  assert.deepEqual([put.url, put.body.dispatch_binding], ["/admin/chat/api/panel/tasks/task-1", "agent_definition"]);
});

test("a bound Action, an unreported or unknown setting and an unguided Action all keep the stored value", async () => {
  const ui = mount();
  ui.edit(row({ dispatch_binding: "agent_definition" }));
  assert.match(ui.howItRuns(), /^Runs the chosen agent directly/);
  assert.equal(ui.convertBox(), null);
  await ui.runnable();
  await ui.submit();
  assert.equal("dispatch_binding" in ui.writes()[0].body, false, "bound stays bound by omission");

  for (const [task, wording] of [
    [row({ id: "old-server" }), "This server does not report how this action runs. Saving here keeps it unchanged."],
    [row({ id: "odd", dispatch_binding: "something_else" }), "This server reports an execution setting this form does not know. Saving here keeps it unchanged."],
  ]) {
    requests = [];
    ui.edit(task);
    assert.equal(ui.howItRuns(), wording);
    assert.equal(ui.convertBox(), null);
    await ui.runnable();
    await ui.submit();
    assert.equal("dispatch_binding" in ui.writes()[0].body, false, task.id);
  }

  requests = [];
  ui.edit(row({ id: "with-steps", step_count: 2, dispatch_binding: "task_definition" }));
  assert.equal(ui.howItRuns(), null, "an unguided Action shows no binding control");
  await ui.submit();
  assert.equal("dispatch_binding" in ui.writes()[0].body, false, "an unguided Action never sends it");
});

test("a refused conversion shows the server's message and keeps the form and the opt-in", async () => {
  const ui = mount();
  ui.edit(row({ dispatch_binding: "task_definition" }));
  ui.convert(true);
  await ui.runnable();
  writeReply = () => Promise.reject(new Error("The selected agent cannot run in this workspace."));
  await ui.submit();
  assert.equal(ui.formError(), "The selected agent cannot run in this workspace.");
  assert.equal(ui.handle.state.showTaskForm, true);
  assert.equal(ui.convertBox().props.checked, true, "the user's choice is not silently dropped");
});

test("the card states the current setting only, never a run's history", () => {
  const badge = (task) => {
    let view;
    act(() => {
      view = TestRenderer.create(createElement(AdminTaskCard, {
        task, isExpanded: false, runs: [], triggeringTask: null, agentModeNameByKey: new Map(),
        taskDependencies: {}, taskDependencyTarget: {}, taskDependencyCondition: {}, taskSteps: {},
        showStepForm: null, editingStep: null, panelAgents: [], runsLoading: null, expandedRun: null, cancellingRun: null,
      }));
    });
    const found = view.root.findAll((node) => node.props["data-testid"] === "action-binding-badge");
    const result = found.length ? { label: text(found[0]), title: found[0].props.title } : null;
    act(() => view.unmount());
    return result;
  };
  const direct = badge(row({ dispatch_binding: "agent_definition" }));
  assert.equal(direct.label, "Runs agent directly");
  assert.match(direct.title, /current setting for its next runs; earlier runs are not labelled with it/);
  // "task_definition" means the Action's own setup: an ordinary agent Action and a deterministic step pipeline
  // (which the backend may run locally) get the same neutral wording, with no worker requirement claimed.
  const ordinary = badge(row({ dispatch_binding: "task_definition" }));
  const deterministic = badge(row({
    dispatch_binding: "task_definition", task_type: "pipeline", step_count: 2,
    config: { local_execution: "deterministic", requires_worker: false },
  }));
  for (const existing of [ordinary, deterministic]) {
    assert.equal(existing.label, "Existing execution setup");
    assert.match(existing.title, /^Keeps its existing execution setup: it runs as it is configured today\./);
    assert.doesNotMatch(`${existing.label} ${existing.title}`, /worker|directly\. No/i);
  }
  assert.equal(badge(row({ dispatch_binding: "something_else" })).label, "Execution setting unknown");
  assert.equal(badge(row()), null, "a row that does not report it gets no guessed badge");
});
