// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/schedulerPreview.test.mjs
//
// Scheduler form with its real state hook and real save handler: readJson is the only
// network seam. Covers the paused-edit regression (no is_active, unchanged cron omitted), the
// preview gate for new/changed schedules, stale preview replies, retry, explicit action choice,
// "Create and activate", and Custom expressions kept byte-for-byte.
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
const PREVIEW = "/admin/chat/api/panel/schedulers/preview";

// Every readJson call (preview hook and save handler alike) is recorded and answered by the test.
const requests = [];
function recordedRead(url, init = {}) {
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null, ...settle });
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
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, setTimeout, clearTimeout, AbortController,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(ADMIN, relative));
}

const loadModule = makeLoader({ "/utils/adminPanelHelpers": { readJson: recordedRead } });
const { AdminNavigationContext } = loadModule("adminNavigation.ts");
const { AdminSchedulersTab } = loadModule("components/AdminSchedulersTab.tsx");
const { useAdminWorkflowState } = loadModule("hooks/useAdminWorkflowState.ts");
const { useAdminTaskSchedulerActions } = loadModule("hooks/useAdminTaskSchedulerActions.ts");

const TASKS = [{ id: "task-a", name: "Nightly Jira Sync" }, { id: "task-b", name: "Weekly Report" }];

function scheduler(overrides) {
  return {
    id: "sched-1", name: "Legacy", description: "", cron_expression: "0 9 30 2 *", task_id: "task-a",
    task_name: "Nightly Jira Sync", is_active: false, owner_id: "u", created_at: "2026-10-01T00:00:00",
    ...overrides,
  };
}

function preview(expression, overrides = {}) {
  return {
    valid: true, cron_expression: expression, timezone: { name: "Europe/Zurich", source: "process_local" },
    scheduling: { owner: "separate_worker", message: "Schedules are registered by a separate scheduler worker. Its time zone and when it applies a change are not confirmed here." },
    next_runs: [
      { at_utc: "2026-10-05T07:00:00Z", local: "2026-10-05T09:00:00+02:00", dst_gap: false, dst_repeat: false },
      { at_utc: "2026-10-25T01:30:00Z", local: "2026-10-25T02:30:00+01:00", dst_gap: false, dst_repeat: true },
    ],
    truncated: false, warning: null, error: null, ...overrides,
  };
}

const NEVER = { valid: false, next_runs: [], error: { code: "cron_never_fires", message: "This schedule never fires: no date matches all of its fields." } };

// One mounted form at a time: an earlier test's debounced preview must not leak into the next.
let mounted = null;

function mount(initialSchedulers = []) {
  if (mounted) act(() => mounted.unmount());
  const handle = {};
  function Harness() {
    const state = useAdminWorkflowState();
    const actions = useAdminTaskSchedulerActions({ ...state, readJson: recordedRead, tasks: TASKS, loadTab: () => {} });
    Object.assign(handle, { state, actions });
    return createElement(AdminSchedulersTab, {
      ctx: {
        ...state, tasks: TASKS, onCreateScheduler: actions.handleCreateScheduler,
        onOpenSchedulerForm: actions.handleOpenSchedulerForm, onCloseSchedulerForm: actions.closeSchedulerForm,
        onSaveScheduler: actions.handleSaveScheduler, onToggleScheduler: actions.handleToggleScheduler,
        onDeleteScheduler: actions.handleDeleteScheduler,
      },
    });
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } }, createElement(Harness)));
  });
  mounted = view;
  act(() => handle.state.setSchedulers(initialSchedulers));
  const byId = (id) => view.root.find((node) => node.props.id === id && typeof node.type === "string");
  const button = (label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
  const form = () => view.root.find((node) => node.type === "form");
  return {
    handle, view, byId, button,
    content: () => text(form()),
    hasId: (id) => view.root.findAll((node) => node.props.id === id && typeof node.type === "string").length > 0,
    change: (id, value) => act(() => byId(id).props.onChange({ target: { value } })),
    nameInput: () => view.root.find((node) => node.type === "input" && node.props.id === "scheduler-form-name"),
    submit: async () => { await act(async () => { await form().props.onSubmit({ preventDefault() {} }); }); },
  };
}

// The preview is debounced (300 ms): let the timer fire, then the request is pending.
const settleDebounce = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 340)); });
const answer = (request, value) => act(async () => { request.resolve(value); });
const saves = () => requests.filter((request) => request.url !== PREVIEW);
const previews = () => requests.filter((request) => request.url === PREVIEW);

test("paused scheduler: a metadata edit omits the unchanged cron and never sends is_active", async () => {
  requests.length = 0;
  const paused = scheduler();
  const ui = mount([paused]);
  act(() => ui.handle.actions.handleOpenSchedulerForm(paused));
  assert.equal(ui.byId("scheduler-schedule-mode").props.value, "custom", "an invalid legacy value opens as Custom");
  assert.equal(ui.byId("scheduler-cron").props.value, "0 9 30 2 *");
  await settleDebounce();
  assert.deepEqual(previews().map((r) => r.body), [{ cron_expression: "0 9 30 2 *", count: 5 }]);
  await answer(previews()[0], preview("0 9 30 2 *", NEVER));
  assert.match(ui.content(), /never fires/);
  assert.match(ui.content(), /unchanged and not valid/);
  assert.match(ui.content(), /Saving keeps this scheduler paused/);
  assert.equal(ui.button("Save changes").props.disabled, false, "a metadata-only edit may proceed");

  act(() => ui.nameInput().props.onChange({ target: { value: "Renamed" } }));
  await ui.submit();
  assert.equal(saves().length, 1);
  const [put] = saves();
  assert.equal(put.method, "PUT");
  assert.deepEqual(put.body, { name: "Renamed", description: "", task_id: "task-a" }, "no cron_expression, no is_active");
  await answer(put, { ...paused, name: "Renamed" });
  assert.equal(ui.handle.state.schedulers[0].is_active, false, "still paused after saving");
});

test("a changed expression cannot be saved until the current preview of it is valid", async () => {
  requests.length = 0;
  const active = scheduler({ cron_expression: "0 9 * * *", is_active: true });
  const ui = mount([active]);
  act(() => ui.handle.actions.handleOpenSchedulerForm(active));
  assert.equal(ui.byId("scheduler-schedule-mode").props.value, "daily");
  ui.change("scheduler-schedule-time", "07:30");
  assert.equal(ui.handle.state.schedulerFormCron, "30 7 * * *");
  assert.equal(ui.button("Save changes").props.disabled, true, "loading preview blocks the save button");
  await ui.submit();
  assert.equal(saves().length, 0, "the real handler refuses too, not only the button");
  assert.match(ui.content(), /Waiting for the next-run preview/);

  await settleDebounce();
  const last = previews().at(-1);
  assert.equal(last.body.cron_expression, "30 7 * * *");
  await answer(last, preview("30 7 * * *"));
  assert.match(ui.content(), /Mon 5 Oct 2026, 09:00 \(UTC\+02:00\)/);
  assert.match(ui.content(), /clocks go back: this time occurs twice/);
  assert.match(ui.content(), /Europe\/Zurich/);
  assert.match(ui.content(), /not confirmed here/);
  await ui.submit();
  const [put] = saves();
  assert.deepEqual(put.body, { name: "Legacy", description: "", task_id: "task-a", cron_expression: "30 7 * * *" });
});

test("stale preview replies never stand in for the current expression; retry recovers a failure", async () => {
  requests.length = 0;
  const ui = mount([]);
  act(() => ui.handle.actions.handleCreateScheduler());
  ui.change("scheduler-schedule-mode", "custom");
  ui.change("scheduler-cron", "0 8 * * *");
  await settleDebounce();
  ui.change("scheduler-cron", "0 9 * * *");
  await settleDebounce();
  const [first, second] = previews();
  assert.deepEqual([first.body.cron_expression, second.body.cron_expression], ["0 8 * * *", "0 9 * * *"]);
  await answer(second, preview("0 9 * * *", NEVER));
  await answer(first, preview("0 8 * * *"));
  assert.match(ui.content(), /never fires/, "the older valid reply arrives last and is dropped");
  assert.equal(ui.button("Create and activate").props.disabled, true);

  ui.change("scheduler-cron", "0 10 * * *");
  await settleDebounce();
  await act(async () => { previews().at(-1).reject(new Error("Service Unavailable")); });
  assert.match(ui.content(), /could not be calculated: Service Unavailable/);
  assert.equal(ui.button("Create and activate").props.disabled, true);
  await act(async () => { ui.button("Retry").props.onClick(); });
  await settleDebounce();
  assert.equal(previews().at(-1).body.cron_expression, "0 10 * * *");
  await answer(previews().at(-1), preview("0 10 * * *"));
  assert.doesNotMatch(ui.content(), /could not be calculated/);
});

test("create needs an explicit action and says it activates; guided weekdays keep names", async () => {
  requests.length = 0;
  const ui = mount([]);
  act(() => ui.handle.actions.handleCreateScheduler());
  assert.equal(ui.byId("scheduler-action").props.value, "", "no action is preselected");
  assert.match(ui.content(), /Creating activates this scheduler\. Choose the action it runs\./);

  ui.change("scheduler-schedule-mode", "weekdays");
  assert.equal(ui.handle.state.schedulerFormCron, "0 9 * * mon-fri");
  await settleDebounce();
  await answer(previews().at(-1), preview("0 9 * * mon-fri"));
  await ui.submit();
  assert.equal(saves().length, 0);
  assert.match(ui.content(), /Choose the action this scheduler runs/);

  ui.change("scheduler-action", "task-b");
  assert.match(ui.content(), /Creating activates this scheduler: it runs the action "Weekly Report" at the times shown\./);
  await ui.submit();
  const [post] = saves();
  assert.equal(post.method, "POST");
  assert.deepEqual(post.body, {
    name: "", description: "", task_id: "task-b", cron_expression: "0 9 * * mon-fri", is_active: true,
  });
});

test("numeric-weekday and other custom expressions stay verbatim; switching to Custom keeps the value", async () => {
  requests.length = 0;
  const numeric = scheduler({ id: "sched-num", cron_expression: "0 9 * * 0-4", is_active: true });
  const ui = mount([numeric]);
  act(() => ui.handle.actions.handleOpenSchedulerForm(numeric));
  assert.equal(ui.byId("scheduler-schedule-mode").props.value, "custom");
  assert.equal(ui.byId("scheduler-cron").props.value, "0 9 * * 0-4");
  await settleDebounce();
  await answer(previews().at(-1), preview("0 9 * * 0-4"));
  await ui.submit();
  assert.equal("cron_expression" in saves()[0].body, false, "an unchanged custom expression is not resent");

  const named = scheduler({ id: "sched-named", cron_expression: "0 9 * * mon-fri", is_active: true });
  act(() => ui.handle.actions.handleOpenSchedulerForm(named));
  assert.equal(ui.byId("scheduler-schedule-mode").props.value, "weekdays", "remounted for the other scheduler");
  ui.change("scheduler-schedule-mode", "custom");
  assert.equal(ui.byId("scheduler-cron").props.value, "0 9 * * mon-fri", "Custom keeps the current expression");
  assert.equal(ui.handle.state.schedulerFormCron, "0 9 * * mon-fri");
});

test("a new scheduler first asks for a frequency: guided choices first, no schedule and no raw cron", async () => {
  requests.length = 0;
  const ui = mount([]);
  act(() => ui.handle.actions.handleCreateScheduler());
  const mode = ui.byId("scheduler-schedule-mode");
  const options = mode.findAllByType("option").map((option) => [option.props.value, text(option), !!option.props.disabled]);
  assert.deepEqual(options, [
    ["", "Choose frequency…", true],
    ["minutes", "Every few minutes", false],
    ["hours", "Every few hours", false],
    ["daily", "Every day", false],
    ["weekdays", "On chosen weekdays", false],
    ["custom", "Custom cron expression", false],
  ], "guided choices before Custom");
  assert.equal(mode.props.value, "", "nothing is selected");
  assert.equal(ui.handle.state.schedulerFormCron, "", "no default expression");
  assert.equal(ui.hasId("scheduler-cron"), false, "no raw cron input");
  assert.doesNotMatch(ui.content(), /Cron expression|\* \* \*/);
  assert.match(ui.content(), /Choose how often the action runs/);
  ui.change("scheduler-action", "task-a");
  await settleDebounce();
  assert.equal(previews().length, 0, "nothing to preview yet");
  assert.equal(ui.button("Create and activate").props.disabled, true);
  await ui.submit();
  assert.equal(saves().length, 0, "nothing is created or activated");

  // Choosing a guided frequency compiles it; the cron stays behind a closed technical disclosure.
  ui.change("scheduler-schedule-mode", "daily");
  assert.equal(ui.byId("scheduler-schedule-mode").props.value, "daily");
  assert.equal(ui.byId("scheduler-schedule-time").props.value, "09:00");
  assert.equal(ui.handle.state.schedulerFormCron, "0 9 * * *");
  assert.equal(ui.hasId("scheduler-cron"), false);
  const details = ui.view.root.findAllByType("details");
  assert.equal(details.length, 1);
  assert.equal(details[0].props.open, undefined, "collapsed by default");
  assert.equal(text(details[0].findByType("summary")), "Technical details");
  assert.match(text(details[0]), /Cron expression: 0 9 \* \* \*/);
  await settleDebounce();
  assert.deepEqual(previews().map((request) => request.body.cron_expression), ["0 9 * * *"]);

  // Custom is a deliberate choice; it shows the raw input with the current expression.
  ui.change("scheduler-schedule-mode", "custom");
  assert.equal(ui.byId("scheduler-cron").props.value, "0 9 * * *");
  assert.equal(ui.view.root.findAllByType("details").length, 0);
});

test("choosing Custom on a blank form gives an empty raw input, not a default", () => {
  requests.length = 0;
  const ui = mount([]);
  act(() => ui.handle.actions.handleCreateScheduler());
  ui.change("scheduler-schedule-mode", "custom");
  assert.equal(ui.byId("scheduler-cron").props.value, "");
  assert.equal(ui.handle.state.schedulerFormCron, "");
});
