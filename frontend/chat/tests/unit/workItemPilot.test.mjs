// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workItemPilot.test.mjs
//
// Review "Nachprüfung" W1–W3 (Work items) and D1/D2 (Documents): cards and tables show our state, never the raw Jira
// status; the Work Item detail is the design system's side panel (Overview | Activity | Jira, Open as page) with Open
// in Jira, Close item and Start workflow in its header and the Jira fields only on the Jira tab; the four KPI tiles are
// gone; a document title never leaves the app and the Documents page has one title.
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { ourStateLabel, ourStateTone } from "../../src/chat/work/workItemState.ts";
import { isWorkItemPage, workItemPageHref } from "../../src/chat/work/workDetailLink.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (root, id) => root.findAll((node) => node.props["data-testid"] === id);
const flush = () => act(async () => { await new Promise((resolve) => setImmediate(resolve)); });

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, Promise,
      encodeURIComponent, performance, setTimeout, clearTimeout,
      window: { location: { origin: "http://localhost", assign: () => {} }, localStorage: { getItem: () => null } }, ...extra,
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
  return loadFile(path.join(SRC, relative));
}

function server(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url: String(url), method: init.method || "GET", body });
    const answer = routes(String(url), init.method || "GET", body);
    return { ok: answer.status < 400, status: answer.status, statusText: "", json: async () => answer.body };
  };
  return { fetch, calls };
}

const item = (overrides = {}) => ({
  id: "wi-1", project_id: "ws-1", source_type: "jira", source_key: "BRD-1", title: "Login fix",
  work_state: "development", sync_state: "unchanged", source_status: "Zu erledigen", assignee: "acc-alex",
  assignee_display: "Jane Doe", priority: "High", labels: [], fix_versions: [], components: [],
  source_url: "https://jira.test/browse/BRD-1", description: "The login fails after rotation.", ...overrides,
});
const EVERYTHING = { items: [], plans: [], events: [], runs: [], missing_setup: [], overrides: [], candidates: [], recommendations: [], links: {}, agent_sessions: [], branches: [], pull_requests: [] };
const everything = () => server(() => ({ status: 200, body: EVERYTHING }));

test("our state: the workflow's label, else the shared words; only exceptions are coloured", () => {
  assert.equal(ourStateLabel(item()), "Development");
  assert.equal(ourStateLabel(item({ work_state: "ready_for_plan" })), "Ready for plan");
  assert.equal(ourStateLabel(item({ work_state: "review" }), [{ is_active: true, states: [{ key: "review", label: "Code review" }] }]), "Code review");
  assert.equal(ourStateTone(item({ work_state: "blocked" })), "problem");
  assert.equal(ourStateTone(item({ work_state: "done" })), "neutral");
  assert.equal(ourStateTone(item({ work_state: "development" })), "info");
});

test("open as page: the address keeps everything and adds work_item_view=page", () => {
  assert.equal(workItemPageHref("?area=work&work_item_id=wi-1"), "/chat?area=work&work_item_id=wi-1&work_item_view=page");
  assert.equal(isWorkItemPage("?work_item_id=wi-1&work_item_view=page"), true);
  assert.equal(isWorkItemPage("?work_item_id=wi-1"), false);
});

test("rendered table: a State column with our state, never the raw Jira status (W1)", () => {
  const { WorkTable } = load("chat/work/WorkAreaViews.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkTable, { items: [item()], syncConfigs: [], onOpenItem: () => {} })); });
  assert.deepEqual(view.root.findAllByType("th").map(text).slice(0, 3), ["Issue", "State", "Assignee"]);
  assert.match(text(view.root), /Development/);
  assert.doesNotMatch(text(view.root), /Zu erledigen/);
  act(() => view.unmount());
});

test("rendered table: newest first, Done hidden until asked, 50 rows per page, the row opens the panel", () => {
  const { WorkTable, workTableRows } = load("chat/work/WorkAreaViews.tsx");
  const day = (n) => new Date(Date.UTC(2026, 0, 1) + n * 86_400_000).toISOString();
  const items = [];
  for (let index = 0; index < 120; index += 1) {
    items.push(item({ id: `wi-${index}`, source_key: `BRD-${index}`, work_state: index % 3 === 0 ? "done" : "development",
      last_source_updated_at: day(index) }));
  }
  const { rows, doneHidden } = workTableRows(items, false);
  assert.equal(doneHidden, 40);
  assert.equal(rows[0].id, "wi-119", "the newest first");
  assert.ok(rows.every((row) => row.work_state !== "done"));
  assert.equal(workTableRows(items, true).rows.length, 120);

  const opened = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkTable, { items, syncConfigs: [], onOpenItem: (entry) => opened.push(entry.id) })); });
  const bodyRows = () => view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.equal(bodyRows().length, 50, "one page of 50");
  assert.equal(view.root.findAllByType("th").map(text).includes("Detail"), false, "no Detail column");
  assert.equal(view.root.findAll((node) => node.type === "button" && text(node) === "Open").length, 0, "no per-row Open button");
  act(() => bodyRows()[0].props.onClick());
  assert.deepEqual(opened, ["wi-119"], "a row click opens the item");
  const pager = byTestId(view.root, "work-table-pager")[0];
  assert.match(text(pager), /^1–50 of 80/);
  act(() => pager.findAll((node) => node.type === "button" && text(node) === "Next")[0].props.onClick());
  assert.equal(bodyRows().length, 30);
  const done = byTestId(view.root, "work-table-done")[0];
  assert.match(text(done), /40 done items hidden\./);
  act(() => done.findByType("button").props.onClick());
  assert.match(text(byTestId(view.root, "work-table-pager")[0]), /^1–50 of 120/, "Show done starts again on the first page");
  act(() => view.unmount());
});

test("rendered detail: a side panel with Overview | Activity | Jira; actions on top; Jira fields only on the Jira tab (W2)", async () => {
  const srv = everything();
  const document = { getElementById: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
  const { WorkItemDetailPanel } = load("chat/work/WorkItemDetailPanel.tsx", { fetch: srv.fetch, document });
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkItemDetailPanel, {
      item: item(), workflows: [], onClose: () => {}, pageHref: "/chat?area=work&work_item_id=wi-1&work_item_view=page",
    }));
  });
  await flush();
  try {
    const panel = byTestId(view.root, "work-item-panel")[0];
    assert.ok(panel, "the design system's side panel");
    assert.equal(panel.props.role, "dialog");
    assert.deepEqual(view.root.findAll((node) => node.props.role === "tab").map(text), ["Overview", "Activity", "Jira"]);
    assert.equal(byTestId(view.root, "work-item-panel-open-page")[0].props.href, "/chat?area=work&work_item_id=wi-1&work_item_view=page");
    assert.equal(byTestId(view.root, "work-item-source-link")[0].props.href, "https://jira.test/browse/BRD-1");
    // Review: Close item is in the "⋯" menu after the primary action, not a button beside ✕.
    assert.equal(byTestId(view.root, "work-item-close").length, 0);
    const actions = byTestId(view.root, "work-item-header-actions")[0];
    const buttons = actions.findAll((node) => node.type === "button");
    assert.deepEqual([buttons.at(-2).props["data-testid"], buttons.at(-1).props["aria-label"]],
      ["work-item-start-workflow", "More actions for BRD-1"]);
    assert.match(byTestId(view.root, "work-item-start-workflow")[0].props.className, /--primary/);
    const overview = text(byTestId(view.root, "work-item-detail")[0]);
    assert.match(overview, /Development/, "our state on Overview");
    assert.match(overview, /The login fails after rotation\./, "the request on Overview");
    assert.doesNotMatch(overview, /Zu erledigen|Jira Source|Issue type/, "no Jira fields on Overview");
    const jiraTab = view.root.findAll((node) => node.props.role === "tab").find((node) => text(node) === "Jira");
    await act(async () => jiraTab.props.onClick());
    const jira = text(byTestId(view.root, "work-item-detail")[0]);
    assert.match(jira, /Jira Source/);
    assert.match(jira, /Zu erledigen/, "the source's own status, as the instance names it, only here");
  } finally { act(() => view.unmount()); }
});

// A Jira item in a Workspace with one startable workflow; `runs` are the item's workflow runs (newest first).
function startableServer(runs = []) {
  return server((url) => {
    if (url.includes("/workflow-runs/startable")) return { status: 200, body: { workflows: [{ key: "deliver", title: "Deliver" }] } };
    if (url.includes("/workflow-runs/runtime-targets")) return { status: 200, body: { default: "server", options: [] } };
    if (url.includes("/workflow-runs?work_item_id=")) return { status: 200, body: { runs } };
    if (url.endsWith("/analysis")) return { status: 200, body: { work_item_id: "wi-1", status: "none", analysis: null } };
    return { status: 200, body: EVERYTHING };
  });
}

async function renderDetail(srv, props = {}) {
  const document = { getElementById: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
  const { WorkItemDetailPanel } = load("chat/work/WorkItemDetailPanel.tsx", { fetch: srv.fetch, document });
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkItemDetailPanel, { item: item(), workflows: [], onClose: () => {}, ...props }));
  });
  await flush();
  return view;
}

test("rendered detail: a lean Overview (state, priority, assignee, request); no run form and no runs section while none (W2)", async () => {
  const srv = startableServer();
  const view = await renderDetail(srv);
  try {
    const overview = text(byTestId(view.root, "work-item-detail")[0]);
    assert.match(text(byTestId(view.root, "work-detail-status")[0]), /Development.*Priority High.*Jane Doe/);
    assert.match(overview, /The login fails after rotation\./);
    assert.equal(byTestId(view.root, "work-run-start").length, 0, "no start form on Overview");
    assert.equal(byTestId(view.root, "work-item-transition").length + byTestId(view.root, "transition-no-workflow").length, 0,
      "no state move on Overview");
    assert.equal(byTestId(view.root, "work-detail-runs").length, 0, "no runs section without runs");
    assert.doesNotMatch(overview, /No workflow run|No active workflow|Choose a workflow|Run on|Start run/);
    const sections = byTestId(view.root, "work-item-detail")[0].findAllByType("h3").map(text);
    for (const title of ["Workflow", "Workflow runs", "Repository Impact", "Pull requests"]) {
      assert.ok(!sections.includes(title), `no empty "${title}" section on Overview`);
    }
    assert.equal(srv.calls.filter((call) => call.url.includes("/workflow-runs/startable")).length, 0, "nothing asked for the form yet");
  } finally { act(() => view.unmount()); }
});

test("rendered detail: Start workflow opens the start form on Overview, Cancel puts it away; starting still works (W2)", async () => {
  const srv = startableServer();
  const view = await renderDetail(srv);
  try {
    const action = byTestId(view.root, "work-item-start-workflow")[0];
    assert.equal(action.props["aria-expanded"], false);
    await act(async () => { action.props.onClick(); });
    await flush();
    assert.equal(byTestId(view.root, "work-item-start-workflow")[0].props["aria-expanded"], true);
    const section = byTestId(view.root, "work-item-start-section")[0];
    assert.ok(section, "the start form appears after the click");
    assert.equal(byTestId(section, "work-run-start").length, 1);
    // No active workflow covers the item: no state move (and no second "publish a workflow" hint).
    assert.equal(byTestId(section, "transition-no-workflow").length, 0);
    act(() => section.find((node) => node.type === "select" && node.props.id === "run-start-wi-1").props.onChange({ target: { value: "deliver" } }));
    const start = byTestId(view.root, "work-run-start-button")[0];
    assert.equal(start.props.disabled, false);
    await act(async () => { start.props.onClick(); });
    await flush();
    const post = srv.calls.find((call) => call.method === "POST" && call.url === "/api/v1/workflow-runs");
    assert.ok(post, "the run is started");
    assert.equal(post.body.workflow_key, "deliver");
    assert.equal(post.body.work_item_id, "wi-1");
    await act(async () => { byTestId(view.root, "work-item-start-cancel")[0].props.onClick(); });
    assert.equal(byTestId(view.root, "work-item-start-section").length, 0, "Cancel puts the form away");
  } finally { act(() => view.unmount()); }
});

test("rendered detail: with a workflow that covers the item, the start form also offers the move; a closed item only moves", async () => {
  const workflows = [{ id: "wf-1", name: "Delivery", is_active: true, project_id: "ws-1", jira_project_keys: ["BRD"], states: [
    { key: "development", label: "Development" }, { key: "review", label: "Review" }] }];
  const view = await renderDetail(startableServer(), { workflows });
  try {
    assert.equal(byTestId(view.root, "work-item-transition").length, 0, "not on Overview");
    await act(async () => { byTestId(view.root, "work-item-start-workflow")[0].props.onClick(); });
    await flush();
    const section = byTestId(view.root, "work-item-start-section")[0];
    assert.equal(byTestId(section, "work-item-transition").length, 1);
  } finally { act(() => view.unmount()); }
  // A closed item starts no run, but can still be moved (e.g. reopened): "Move item" opens only the move.
  const closed = await renderDetail(startableServer(), { workflows, item: item({ work_state: "done" }) });
  try {
    const action = byTestId(closed.root, "work-item-start-workflow")[0];
    assert.equal(text(action), "Move item");
    await act(async () => { action.props.onClick(); });
    await flush();
    const section = byTestId(closed.root, "work-item-start-section")[0];
    assert.equal(byTestId(section, "work-run-start").length, 0);
    assert.equal(byTestId(section, "work-item-transition").length, 1);
  } finally { act(() => closed.unmount()); }
  const closedNoWorkflow = await renderDetail(startableServer(), { item: item({ work_state: "done" }) });
  try {
    assert.equal(byTestId(closedNoWorkflow.root, "work-item-start-workflow").length, 0, "nothing to start or move");
  } finally { act(() => closedNoWorkflow.unmount()); }
});

test("rendered detail: the item's runs as a short list, newest first, the rest counted (W2)", async () => {
  const run = (index) => ({ id: `run-${index}`, title: `Run ${index}`, workflow_key: "deliver", workflow_kind: "delivery",
    status: "succeeded", waiting_kind: null, pause_reason: null, outcome: null, session_id: null });
  const view = await renderDetail(startableServer(Array.from({ length: 7 }, (_, index) => run(index + 1))));
  try {
    const runs = byTestId(view.root, "work-detail-runs")[0];
    assert.deepEqual(runs.findAllByType("li").map((node) => text(node.findAllByType("span")[0])),
      ["Run 1", "Run 2", "Run 3", "Run 4", "Run 5"]);
    assert.match(text(runs), /2 earlier runs/);
    assert.equal(byTestId(runs, "work-run-start").length, 0, "no start form in the list");
  } finally { act(() => view.unmount()); }
});

test("rendered detail as a page: no dialog, a way back to the list (W2)", async () => {
  const srv = everything();
  let closed = 0;
  const { WorkItemDetailPanel } = load("chat/work/WorkItemDetailPanel.tsx", { fetch: srv.fetch, document: { getElementById: () => null } });
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkItemDetailPanel, { item: item(), workflows: [], onClose: () => { closed += 1; }, mode: "page" }));
  });
  await flush();
  try {
    assert.equal(view.root.findAll((node) => node.props.role === "dialog").length, 0);
    await act(async () => byTestId(view.root, "work-item-back")[0].props.onClick());
    assert.equal(closed, 1);
  } finally { act(() => view.unmount()); }
});

test("source: the KPI tiles are gone; the detail never squeezes the board into a column (W2, W3)", () => {
  const workspace = fs.readFileSync(path.join(SRC, "chat/work/WorkAreaWorkspace.tsx"), "utf8");
  assert.doesNotMatch(workspace, /WorkSummary|has-detail/);
  const filters = fs.readFileSync(path.join(SRC, "chat/work/WorkFilters.tsx"), "utf8");
  assert.doesNotMatch(filters, /Requested for agents|Active intakes|Needs attention/);
});

test("source: Documents has one title; a title opens the document here (D1, D2)", () => {
  const inventory = fs.readFileSync(path.join(SRC, "chat/knowledge/KnowledgeSourceInventory.tsx"), "utf8");
  assert.doesNotMatch(inventory, /Documents and repository evidence/);
  assert.doesNotMatch(inventory, /knowledge-sources__title">\{synced\?\.url/);
  assert.match(inventory, /Open in \$\{synced\.sourceName\}/);
});
