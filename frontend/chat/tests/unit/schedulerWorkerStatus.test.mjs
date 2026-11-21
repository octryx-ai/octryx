// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/schedulerWorkerStatus.test.mjs
//
// Scheduler worker application status: absent/malformed/unknown data reads "Status not
// available", never Applied; a next run shows only when applied and current; the row dot follows
// the worker, not the configured switch. "Check worker status" is one request per click, never a
// timer; its reply is merged so a save, pause or delete that lands while it is pending is kept,
// an open form keeps its edits, and a failure keeps the last known rows.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { presentWorkerApplication, readWorkerApplication } from "../../src/admin/components/scheduler/workerApplicationModel.ts";
import { mergeStatusCheck } from "../../src/admin/components/scheduler/useSchedulerStatusCheck.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2026-10-04T12:00:00Z");
const FUTURE = "2026-10-05T07:00:00Z";

// ---- presenter -------------------------------------------------------------------------------

test("absent, malformed or unknown data is never read as applied", () => {
  const unknown = [
    undefined,
    null,
    "applied",
    {},
    { status: "running", next_run_at: null, timezone: null },
    { status: "applied" },
    { status: "applied", next_run_at: 123, timezone: "UTC" },
    { status: "applied", next_run_at: FUTURE, timezone: 5 },
  ];
  for (const value of unknown) {
    assert.equal(readWorkerApplication(value), null, JSON.stringify(value));
    const view = presentWorkerApplication(value, NOW);
    assert.deepEqual([view.tone, view.label, view.nextRun], ["unknown", "Status not available", null]);
  }
});

test("each documented status has its own meaning; copy is scoped to new queue entries of this schedule", () => {
  const view = (status, next_run_at = null, timezone = null) =>
    presentWorkerApplication({ status, next_run_at, timezone }, NOW);
  const paused = view("paused");
  assert.equal(paused.label, "Paused");
  assert.ok(paused.detail.startsWith("This schedule adds no new runs to the queue"), "about this schedule only");
  assert.ok(paused.detail.includes("not cancelled") && paused.detail.includes("other triggers of the linked action"));
  const unavailable = view("worker_unavailable");
  assert.deepEqual([unavailable.tone, unavailable.label], ["problem", "No scheduling worker"]);
  assert.ok(unavailable.detail.includes("adds no new runs to the queue"));
  assert.ok(unavailable.detail.includes("Runs already queued are not affected"), "queued work is not claimed to stop");
  assert.ok(!unavailable.detail.includes("no runs start"));
  assert.deepEqual([view("pending").tone, view("pending").label], ["waiting", "Waiting for the worker"]);
  assert.equal(view("invalid_schedule", null, "UTC").label, "Schedule not usable");
  for (const status of ["paused", "pending", "worker_unavailable", "invalid_schedule"]) {
    assert.equal(view(status, FUTURE, "UTC").nextRun, null, `${status} never shows a next run`);
  }

  const applied = view("applied", FUTURE, "Europe/Zurich");
  assert.deepEqual([applied.tone, applied.label], ["applied", "Applied by the worker"]);
  assert.equal(applied.nextRun, "Mon 5 Oct 2026, 09:00 (Europe/Zurich)", "shown in the worker's zone");
  assert.equal(view("applied", FUTURE, null).nextRun, "Mon 5 Oct 2026, 07:00 (UTC)");
  assert.equal(view("applied", FUTURE, "Not/AZone").nextRun, "Mon 5 Oct 2026, 07:00 (UTC)", "unknown zone falls back to UTC");
  assert.equal(view("applied", null, "UTC").nextRun, null);
});

test("a past or unreadable next run is not presented as upcoming, even when applied", () => {
  for (const next of ["2026-10-04T11:59:00Z", "2026-10-04T12:00:00Z", "2026-10-05T07:00:00+00:00Z", "soon"]) {
    const view = presentWorkerApplication({ status: "applied", next_run_at: next, timezone: "UTC" }, NOW);
    assert.deepEqual([view.tone, view.label, view.nextRun], ["waiting", "Applied, next run not current", null], next);
  }
});

// ---- merge of a status reply with local writes made while it was pending -----------------------

const status = (value) => ({ status: value, next_run_at: null, timezone: null });
const row = (id, overrides = {}) => ({
  id, name: `Scheduler ${id}`, description: "", cron_expression: "0 9 * * mon-fri", task_id: "task-a",
  task_name: "Nightly Jira Sync", is_active: true, owner_id: "u", created_at: "2026-10-01T00:00:00",
  worker_application: status("pending"), ...overrides,
});

test("merge: no local write in flight takes the reply as is, including server-side changes", () => {
  const snapshot = [row("a"), row("b")];
  const fetched = [row("c"), row("a", { worker_application: status("applied") })];
  assert.equal(mergeStatusCheck(snapshot, snapshot, fetched), fetched);
});

test("merge: local writes in flight win; untouched rows take the reply; nothing deleted comes back", () => {
  const [a, b, c, d] = [row("a"), row("b"), row("c"), row("d")];
  const snapshot = [a, b, c, d];
  const pausedB = row("b", { is_active: false, worker_application: status("paused") });
  const created = row("new");
  const current = [created, a, pausedB, d]; // created "new", paused "b", deleted "c"
  const fetched = [
    row("a", { worker_application: status("applied") }),
    row("b", { worker_application: status("applied") }), // read before the pause
    row("c"), // read before the delete
    row("other"), // listed by the server, unknown here: not added while the list changed
  ]; // "d" is gone on the server
  assert.deepEqual(mergeStatusCheck(snapshot, current, fetched), [created, fetched[0], pausedB]);
});

// ---- rendered tab with the real state hook and real scheduler actions --------------------------

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const LIST = "/admin/chat/api/panel/schedulers";
const requests = [];
function recordedRead(url, init = {}) {
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null, ...settle });
  return promise;
}
// Every timer the rendered modules schedule is counted: a status check must schedule none.
const timers = { timeouts: 0, intervals: 0 };
const countedTimers = {
  setTimeout: (...args) => { timers.timeouts += 1; return setTimeout(...args); },
  setInterval: (...args) => { timers.intervals += 1; return setInterval(...args); },
};

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
      module, exports: module.exports, console, clearTimeout, clearInterval, AbortController, Date, Intl,
      ...countedTimers, confirm: () => true,
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

const TASKS = [{ id: "task-a", name: "Nightly Jira Sync" }];
const APPLIED = { status: "applied", next_run_at: "2099-01-05T08:00:00Z", timezone: "UTC" };
const ROWS = [
  row("applied", { worker_application: APPLIED }),
  row("legacy", { worker_application: undefined }), // no worker_application at all
  row("paused", { is_active: false, worker_application: status("paused") }),
];

let mounted = null;
function mount(initial = ROWS) {
  if (mounted) act(() => mounted.unmount());
  requests.length = 0;
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
  act(() => handle.state.setSchedulers(initial));
  const byClass = (root, name) => root.findAll((node) => typeof node.type === "string" && String(node.props.className || "").split(" ").includes(name));
  // The schedulers are a DataTable; a row opens the side panel with the details and actions.
  const items = () => view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  const item = (id) => items().find((node) => node.props["data-row-key"] === id);
  const state = (id) => view.root.find((node) => typeof node.type === "string" && node.props["data-testid"] === `scheduler-state-${id}`);
  const ui = {
    handle, view,
    // Built in this realm: rows written by the actions are arrays of the module's realm.
    ids: () => Array.from(handle.state.schedulers, (scheduler) => scheduler.id),
    rowCount: () => items().length,
    statusLabel: (id) => text(state(id)),
    stateTone: (id) => state(id).props["data-tone"],
    stateReason: (id) => state(id).props.title,
    // The configured switch is Pause / Resume in the row's side panel.
    switchOn: (id) => {
      act(() => item(id).props.onClick());
      const on = view.root.findAll((node) => node.type === "button" && text(node).trim() === "Pause").length > 0;
      act(() => view.root.find((node) => node.type === "button" && node.props["data-testid"] === "scheduler-detail-panel-close").props.onClick());
      return on;
    },
    rowClasses: (id) => item(id).props.className.split(/\s+/).filter(Boolean),
    details: () => byClass(view.root, "admin-scheduler__worker-detail").length,
    intro: () => byClass(view.root, "admin-scheduler__explainer").length,
    checkHint: () => byClass(view.root, "admin-scheduler__check")[0].findAll((node) => node.props.className === "admin-panel__hint").map(text).join(""),
    checkError: () => byClass(view.root, "admin-scheduler__check")[0].findAll((node) => node.props.className === "admin-panel__form-error").map(text),
    button: (label) => view.root.find((node) => node.type === "button" && text(node).trim() === label),
    forms: () => view.root.findAllByType("form").length,
    startCheck: () => act(async () => { ui.button("Check worker status").props.onClick(); }),
    answer: (request, value) => act(async () => { request.resolve(value); }),
  };
  return ui;
}
const pending = (method, url = LIST) => requests.filter((request) => request.method === method && request.url.startsWith(url));

test("rows show worker status as their state; the configured switch stays in the side panel", () => {
  const ui = mount();
  assert.deepEqual(ui.ids().map(ui.statusLabel), ["Applied by the worker", "Status not available", "Paused"]);
  assert.deepEqual(ui.ids().map(ui.stateTone), ["neutral", "neutral", "neutral"], "only exceptions are coloured");
  assert.match(ui.stateReason("legacy"), /did not report whether the scheduling worker has applied/, "the reason is the tooltip");
  assert.equal(ui.details(), 0, "the worker's explanation is not printed in the table (20 lines per row)");
  assert.deepEqual(ui.ids().map(ui.switchOn), [true, true, false], "the configured state stays on the switch");
  assert.equal(ui.checkHint(), "", "no as-of line before a check; what the status means is in the page help");
  assert.equal(requests.length, 0, "nothing is fetched without an explicit check");
});

test("a paused row stays readable with its own marker; the caveats live in the page help, not on the page", () => {
  const ui = mount();
  assert.deepEqual(ui.ids().map((id) => ui.rowClasses(id).some((name) => /inactive|disabled/.test(name))), [false, false, false], "no shared fade");
  assert.deepEqual(ui.ids().map((id) => ui.statusLabel(id) === "Paused"), [false, false, true], "configured pause is labelled");
  act(() => ui.view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "applied").props.onClick());
  assert.equal(ui.details(), 1, "the side panel spells out the worker status");
  const paused = ui.handle.state.schedulers.find((scheduler) => scheduler.id === "paused");
  assert.equal(paused.is_active, false);

  assert.equal(ui.intro(), 0, "no explanatory list on the page");
  const help = fs.readFileSync(new URL("../../help/admin/schedulers.md", import.meta.url), "utf8");
  assert.match(help, /decides \*\*when\*\*/);
  assert.match(help, /already queued or running are not cancelled/);
  assert.match(help, /not whether a run succeeded/);
});

test("a normal check is one request, schedules no timer and keeps an open form's edits", async () => {
  const ui = mount();
  const before = { ...timers };
  await ui.startCheck();
  assert.equal(pending("GET").length, 1);
  assert.equal(ui.button("Checking…").props.disabled, true, "no concurrent checks");
  await ui.answer(pending("GET")[0], ROWS.map((item) => (item.id === "legacy" ? { ...item, worker_application: status("pending") } : item)));
  assert.equal(ui.statusLabel("legacy"), "Waiting for the worker");
  assert.ok(ui.checkHint().startsWith("Checked "), ui.checkHint());
  assert.deepEqual(timers, before, "no timer or interval: nothing polls");

  act(() => ui.handle.actions.handleOpenSchedulerForm(ROWS[1]));
  act(() => ui.handle.state.setSchedulerFormName("Edited name"));
  await ui.startCheck();
  await ui.answer(pending("GET")[1], ROWS);
  assert.equal(ui.forms(), 1, "the form stays open");
  assert.equal(ui.handle.state.schedulerFormName, "Edited name", "the draft survives the check");
});

test("a pause that lands while a check is pending is not undone by the older reply", async () => {
  const ui = mount();
  await ui.startCheck();
  await act(async () => { void ui.handle.actions.handleToggleScheduler("applied", true); });
  const [put] = pending("PUT");
  assert.deepEqual(put.body, { is_active: false });
  await ui.answer(put, row("applied", { is_active: false, worker_application: status("paused") }));
  // The status read was served before the pause: it still lists the row active and applied.
  await ui.answer(pending("GET")[0], ROWS.map((item) => (item.id === "legacy" ? { ...item, worker_application: status("pending") } : item)));
  assert.equal(ui.switchOn("applied"), false, "still paused");
  assert.equal(ui.statusLabel("applied"), "Paused");
  assert.equal(ui.statusLabel("legacy"), "Waiting for the worker", "untouched rows still take the reply");
});

test("a save that lands while a check is pending keeps its result and the form flow", async () => {
  const ui = mount();
  act(() => ui.handle.actions.handleOpenSchedulerForm(ROWS[0]));
  act(() => ui.handle.state.setSchedulerFormName("Renamed"));
  await ui.startCheck();
  await act(async () => { void ui.handle.actions.handleSaveScheduler({ preventDefault() {} }); });
  const [put] = pending("PUT");
  assert.equal(put.body.name, "Renamed");
  await ui.answer(put, row("applied", { name: "Renamed", worker_application: status("pending") }));
  await ui.answer(pending("GET")[0], ROWS);
  const saved = ui.handle.state.schedulers.find((scheduler) => scheduler.id === "applied");
  assert.equal(saved.name, "Renamed", "the older read does not restore the old name");
  assert.equal(ui.statusLabel("applied"), "Waiting for the worker");
});

test("a delete that lands while a check is pending is not brought back", async () => {
  const ui = mount();
  await ui.startCheck();
  await act(async () => { void ui.handle.actions.handleDeleteScheduler("legacy", "Scheduler legacy"); });
  await ui.answer(pending("DELETE")[0], { status: "deleted" });
  assert.deepEqual(ui.ids(), ["applied", "paused"]);
  await ui.answer(pending("GET")[0], ROWS); // served before the delete
  assert.deepEqual(ui.ids(), ["applied", "paused"]);
  assert.equal(ui.rowCount(), 2);
});

test("a failed check is visible and keeps the last known rows and the form", async () => {
  const ui = mount();
  act(() => ui.handle.actions.handleCreateScheduler());
  await ui.startCheck();
  await act(async () => { pending("GET")[0].reject(new Error("Service Unavailable")); });
  assert.deepEqual(ui.checkError(), ["Worker status could not be checked: Service Unavailable. The list shows the last known status."]);
  assert.deepEqual(ui.ids(), ["applied", "legacy", "paused"]);
  assert.equal(ui.statusLabel("applied"), "Applied by the worker");
  assert.equal(ui.forms(), 1, "the create form stays");
  assert.equal(ui.button("Check worker status").props.disabled, false, "the user can try again");
});

test("rows owned by Work › Intake pause and delete; only they skip Edit", async () => {
  const intake = row("intake", { managed_by_work: true, read_only: true });
  const ui = mount([intake]);
  const open = (id) => act(() => ui.view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === id).props.onClick());
  const footer = () => ui.view.root.findAll((node) => node.type === "button" && node.props["data-testid"] === "scheduler-panel-toggle").map(text);
  const edits = () => ui.view.root.findAll((node) => node.type === "button" && text(node).trim() === "Edit").length;
  const menus = () => ui.view.root.findAll((node) => node.type === "button" && /^More actions for /.test(node.props["aria-label"] || "")).length;
  assert.equal(menus(), 1, "every row has its ⋯ menu");
  open("intake");
  assert.deepEqual(footer(), ["Pause"]);
  assert.equal(edits(), 0, "edited in Work › Intake");

  await act(async () => { void ui.handle.actions.handleToggleScheduler("intake", true); });
  assert.deepEqual(requests.map((request) => [request.method, request.url, request.body]),
    [["PUT", `${LIST}/intake`, { is_active: false }]]);
  await act(async () => { void ui.handle.actions.handleDeleteScheduler("intake", "x"); });
  assert.deepEqual([requests.at(-1).method, requests.at(-1).url], ["DELETE", `${LIST}/intake`]);
});
