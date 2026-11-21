// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionRunStatus.test.mjs
//
// Action run status after Execute / Cancel / Refresh, rendered with the real header, list,
// card and runs panel, useAdminTaskState / useAdminWorkflowState and useAdminTaskCoreActions.
// readJson is the only stub: GETs stay pending until the test answers them; POSTs succeed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { mergeTaskSummary } from "../../src/admin/hooks/actionRunStatusSync.ts";
import * as loadingState from "../../src/layout/LoadingState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

let requests = [];
let failPost = null;
const alerts = [];
const timers = { timeouts: 0, intervals: 0 };
function stubRead(url, init = {}) {
  const method = init.method || "GET";
  if (method !== "GET") {
    requests.push({ url, method });
    return failPost ? Promise.reject(new Error(failPost)) : Promise.resolve({ status: "queued", task_run_id: "run-new" });
  }
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, method, ...settle });
  return promise;
}

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    if (name.endsWith("/layout/LoadingState")) return loadingState;
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
      module, exports: module.exports, console, Date, Map,
      setTimeout: (...args) => { timers.timeouts += 1; return setTimeout(...args); },
      setInterval: (...args) => { timers.intervals += 1; return setInterval(...args); },
      clearTimeout, clearInterval, AbortController,
      alert: (message) => alerts.push(message), confirm: () => true,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(ADMIN, relative));
}

const loadModule = makeLoader({ "/utils/adminPanelHelpers": { readJson: stubRead } });
const { AdminNavigationContext } = loadModule("adminNavigation.ts");
const { AdminTasksTabHeader } = loadModule("components/AdminTasksTabHeader.tsx");
const { AdminTasksList } = loadModule("components/AdminTasksList.tsx");
const { useAdminTaskState } = loadModule("hooks/useAdminTaskState.ts");
const { useAdminWorkflowState } = loadModule("hooks/useAdminWorkflowState.ts");
const { useAdminTaskCoreActions } = loadModule("hooks/useAdminTaskCoreActions.ts");

const task = (overrides = {}) => ({
  id: "task-1", name: "Nightly digest", description: "", task_type: "agent_run", agent_type: "diagnosis",
  is_active: true, config: {}, run_count: 0, running_count: 0, queued_count: 0, last_run_status: null,
  last_run_at: null, step_count: 0, next_queue_priority: null, ...overrides,
});
const queuedRun = (overrides = {}) => ({
  id: "run-new-123456", task_id: "task-1", session_id: null, status: "queued", started_by: "u",
  started_at: null, completed_at: null, error: null, duration_seconds: null, steps_log: [],
  queue_priority: 5, queue_status: "pending", queue_required_domain: "any", queued_at: "2026-10-04T10:00:00",
  estimated_wait_seconds: 0, ...overrides,
});
const QUEUED_SUMMARY = { run_count: 1, queued_count: 1, last_run_status: "queued", next_queue_priority: 5 };

let mounted = null;
function mount(initialTasks = [task()]) {
  if (mounted) act(() => mounted.unmount());
  requests = [];
  alerts.length = 0;
  failPost = null;
  const handle = {};
  function Harness() {
    const state = useAdminTaskState();
    const workflow = useAdminWorkflowState();
    const actions = useAdminTaskCoreActions({
      args: { ...workflow, ...state, readJson: stubRead }, loadTaskSteps: async () => {},
    });
    Object.assign(handle, { state, actions });
    const noop = () => {};
    const ctx = new Proxy(
      {
        ...workflow, ...state, agentModeNameByKey: new Map(),
        loadTaskRuns: actions.loadTaskRuns, onCancelRun: actions.handleCancelRun,
        onExpandTask: actions.handleExpandTask, onTriggerTask: actions.handleTriggerTask,
        onOpenTaskForm: actions.handleOpenTaskForm, onCloseTaskForm: actions.closeTaskForm,
      },
      { get: (target, key) => (key in target ? target[key] : noop) },
    );
    return createElement("div", null, createElement(AdminTasksTabHeader, { ctx }), createElement(AdminTasksList, { ctx }));
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } }, createElement(Harness)));
  });
  mounted = view;
  act(() => handle.state.setTasks(initialTasks));
  const button = (label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
  const gets = (suffix) => requests.filter((request) => request.method === "GET" && request.url.endsWith(suffix));
  return {
    handle, view, button, gets,
    posts: () => requests.filter((request) => request.method === "POST"),
    header: () => text(view.root.find((node) => node.props["data-testid"] === "actions-summary")),
    lastRun: () => text(view.root.find((node) => node.props.className === "task-item__last-run")),
    history: () => view.root.findAll((node) => node.type === "span" && text(node).startsWith("Execution History")).map(text)[0],
    queueCells: () => view.root.findAll((node) => node.type === "tr" && String(node.props.className || "").includes("task-run--clickable"))
      .map((row) => text(row.findAllByType("td")[2])),
    queuedNote: () => view.root.findAll((node) => node.props["data-testid"] === "task-runs-queued-note").map(text)[0] ?? null,
    error: () => view.root.findAll((node) => node.props.role === "alert").map(text)[0] ?? null,
    answer: (request, value) => act(async () => { request.resolve(value); }),
    fail: (request, message) => act(async () => { request.reject(new Error(message)); }),
  };
}

test("Execute refreshes the run list and the Action summary once, showing the accepted queued run honestly", async () => {
  const ui = mount();
  act(() => { ui.handle.actions.handleExpandTask("task-1"); });
  await ui.answer(ui.gets("/runs")[0], []);
  assert.equal(ui.lastRun(), "Never executed");
  assert.equal(ui.history(), "Execution History (0)");
  const before = { ...timers };

  await act(async () => { ui.button("▶ Execute").props.onClick(); });
  assert.equal(ui.posts().length, 1, "one execution request");
  assert.equal(ui.posts()[0].url, "/admin/chat/api/panel/tasks/task-1/run");
  assert.equal(ui.gets("/runs").length, 2, "the cached list is asked again");
  assert.equal(ui.gets("/panel/tasks").length, 1, "and the Action summary");

  await ui.answer(ui.gets("/panel/tasks")[0], [task(QUEUED_SUMMARY), task({ id: "other", queued_count: 7 })]);
  await ui.answer(ui.gets("/runs")[1], [queuedRun()]);
  assert.match(ui.header(), /1 queued/);
  assert.ok(ui.lastRun().startsWith("●"), ui.lastRun());
  assert.ok(ui.lastRun().includes("queued"));
  assert.equal(ui.history(), "Execution History (1)");
  assert.deepEqual(ui.queueCells(), ["p5 · waiting"], "no invented ~0s estimate");
  assert.ok(ui.queuedNote().startsWith("1 run is queued and not started yet."));
  assert.ok(ui.queuedNote().includes("does not report why it is still waiting"));
  assert.equal(ui.handle.state.tasks.length, 1, "only this Action's summary is taken over");
  assert.deepEqual(timers, before, "no timer and no polling");
  assert.equal(ui.posts().length, 1, "never executed twice");
});

test("Cancel refreshes the card and counts, not only the row", async () => {
  const ui = mount([task(QUEUED_SUMMARY)]);
  act(() => { ui.handle.actions.handleExpandTask("task-1"); });
  await ui.answer(ui.gets("/runs")[0], [queuedRun()]);
  await act(async () => { ui.button("Cancel").props.onClick(); });
  assert.deepEqual(ui.posts().map((request) => request.url), ["/admin/chat/api/panel/tasks/task-1/runs/run-new-123456/cancel"]);
  await ui.answer(ui.gets("/panel/tasks")[0], [task({ run_count: 1, queued_count: 0, last_run_status: "cancelled" })]);
  await ui.answer(ui.gets("/runs")[1], [queuedRun({ status: "cancelled", queue_status: "cancelled" })]);
  assert.match(ui.header(), /0 queued/);
  assert.ok(ui.lastRun().includes("cancelled"));
  assert.equal(ui.queuedNote(), null);
});

test("Refresh asks again although runs are cached; a failed refresh keeps the rows and says so", async () => {
  const ui = mount([task(QUEUED_SUMMARY)]);
  act(() => { ui.handle.actions.handleExpandTask("task-1"); });
  await ui.answer(ui.gets("/runs")[0], [queuedRun()]);
  await act(async () => { ui.button("Refresh").props.onClick(); });
  assert.equal(ui.gets("/runs").length, 2, "the cache does not swallow a manual refresh");
  assert.equal(ui.button("Refreshing…").props.disabled, true, "rows stay visible while refreshing");
  await ui.fail(ui.gets("/runs")[1], "Service Unavailable");
  assert.equal(ui.error(), "Run status could not be refreshed: Service Unavailable. The list shows the last known status.");
  assert.deepEqual(ui.queueCells(), ["p5 · waiting"], "last known rows kept");
  assert.match(ui.header(), /1 queued/, "summary unchanged");

  await act(async () => { ui.button("Refresh").props.onClick(); });
  await ui.answer(ui.gets("/panel/tasks").at(-1), [task({ ...QUEUED_SUMMARY, queued_count: 0, running_count: 1, last_run_status: "running" })]);
  await ui.answer(ui.gets("/runs").at(-1), [queuedRun({ status: "running", estimated_wait_seconds: 40 })]);
  assert.equal(ui.error(), null, "a successful refresh clears the error");
  assert.deepEqual(ui.queueCells(), ["p5 · ~40s"], "a positive estimate is shown");
});

test("an older reply never overwrites a newer one; local edits survive a summary refresh", async () => {
  const ui = mount([task(QUEUED_SUMMARY)]);
  act(() => { ui.handle.actions.handleExpandTask("task-1"); });
  const expandLoad = ui.gets("/runs")[0];
  await act(async () => { ui.button("Refresh").props.onClick(); });
  const refresh = ui.gets("/runs")[1];
  act(() => ui.handle.state.setTasks((prev) => prev.map((row) => ({ ...row, name: "Renamed locally" }))));
  await ui.answer(ui.gets("/panel/tasks")[0], [task({ ...QUEUED_SUMMARY, name: "Old server name", queued_count: 0, last_run_status: "success" })]);
  await ui.answer(refresh, [queuedRun({ status: "success", queue_status: "completed" })]);
  await ui.answer(expandLoad, [queuedRun()]); // the slower, older request
  assert.equal(ui.handle.state.taskRuns["task-1"][0].status, "success");
  assert.equal(ui.handle.state.tasks[0].name, "Renamed locally", "only summary fields are taken over");
  assert.equal(ui.handle.state.tasks[0].last_run_status, "success");
});

test("a failed Execute reports the error and does not refresh or retry", async () => {
  const ui = mount();
  // Execute is in the Action's side panel, which the row opens (and which loads its runs once).
  act(() => { ui.handle.actions.handleExpandTask("task-1"); });
  const before = ui.gets("/runs").length + ui.gets("/panel/tasks").length;
  failPost = "Action is paused";
  await act(async () => { ui.button("▶ Execute").props.onClick(); });
  // The existing handler shows the error through alert (its message is lost across the test's realms).
  assert.equal(alerts.length, 1);
  assert.equal(ui.posts().length, 1);
  assert.equal(ui.gets("/runs").length + ui.gets("/panel/tasks").length, before, "nothing refreshed after the failure");
});

test("Actions are table rows; a row opens the Action detail in the side panel and its close button closes it", () => {
  const ui = mount();
  const rows = () => ui.view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.deepEqual(rows().map((row) => row.props["data-row-key"]), ["task-1"]);
  const panels = () => ui.view.root.findAll((node) => typeof node.type === "string" && node.props["data-testid"] === "action-detail-panel");
  assert.equal(panels().length, 0, "no card or detail before a row is opened");
  act(() => rows()[0].props.onClick());
  assert.equal(panels().length, 1);
  assert.equal(ui.handle.state.expandedTask, "task-1", "the same expand handler loads steps, dependencies and runs");
  act(() => ui.view.root.find((node) => node.type === "button" && node.props["data-testid"] === "action-detail-panel-close").props.onClick());
  assert.equal(panels().length, 0);
  assert.equal(ui.handle.state.expandedTask, null);
});

test("the summary merge keeps every non-summary field and ignores an unlisted Action", () => {
  const current = [task({ name: "Local", config: { a: 1 } }), task({ id: "other" })];
  const merged = mergeTaskSummary(current, [task({ name: "Server", run_count: 3, last_run_status: "error" })], "task-1");
  assert.equal(merged[0].name, "Local");
  assert.deepEqual(merged[0].config, { a: 1 });
  assert.deepEqual([merged[0].run_count, merged[0].last_run_status], [3, "error"]);
  assert.equal(merged[1], current[1]);
  assert.equal(mergeTaskSummary(current, [], "task-1"), current, "an Action the list no longer has is not guessed about");
});
