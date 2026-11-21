// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workPlanComposition.test.mjs
//
// The real Work area composition (judge findings): WorkAreaWorkspace → WorkPlanList +
// WorkItemDetailPanel → WorkChangePlans, against an in-memory plan backend. A decision on an older
// plan updates the detail and the list without Refresh; the review queue drops a decided plan; a
// failed decision changes nothing; mutations are exclusive; a slow earlier load never wins.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as loadingState from "../../src/layout/LoadingState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const WORK_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/work");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const buttons = (root, pattern) => root.findAll((node) => node.type === "button" && pattern.test(text(node)));
const flush = () => act(async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); });

// Loads real modules from src/chat/work (transpiled), replacing only the given suffixes.
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
      module, exports: module.exports, window: globalThis.window, document: globalThis.document,
      URL, URLSearchParams, console, require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(WORK_DIR, relative));
}

function fakeWindow(search) {
  const win = { location: {}, history: {}, localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true };
  const go = (href) => { const url = new URL(href, "https://octryx.example"); win.location.href = url.href; win.location.search = url.search; win.location.origin = url.origin; };
  win.history.replaceState = (_state, _title, url) => go(url);
  go(`/chat${search}`);
  return win;
}

const Null = () => null;
const ITEM = {
  id: "item-far", source_key: "OPS-2", title: "Synthetic item", description: "Full item", source_status: "Open",
  work_state: "planning", sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [], source_fields: {},
};

function fullPlan(id, version, status) {
  return {
    id, work_item_id: ITEM.id, workflow_id: null, supersedes_plan_id: null, version, status, title: `Plan ${id}`,
    understood_request: `Request of ${id}`, assumptions: [], open_questions: [], affected_repositories: [], change_units: [],
    proposed_branches: [], planned_files: [], validation_plan: [], security_risks: [], reviewer_recommendations: [],
    required_approvals: [], expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {}, jira_sync_preview: {},
    created_by: "u1", created_at: "2026-10-01T12:00:00", updated_at: `2026-10-01T12:0${version}:00`,
  };
}

// An in-memory backend with the list contract: the queue is persisted ready_for_review.
function fakeBackend({ failDecision = false } = {}) {
  const plans = [fullPlan("plan-v2", 2, "ready_for_review"), fullPlan("plan-v1", 1, "ready_for_review")];
  const calls = { list: [], decide: [], generate: 0, item: 0 };
  const summaryOf = (plan) => ({
    id: plan.id, work_item_id: plan.work_item_id, version: plan.version, status: plan.status, title: plan.title, workflow_id: null,
    supersedes_plan_id: null, plan_type: null, open_questions_count: 0, acceptance_criteria_count: 0, change_unit_count: 0,
    created_by: "u1", created_by_name: "Ada Planner", decided_by: null, created_at: plan.created_at, updated_at: plan.updated_at,
    decided_at: plan.decided_at ?? null, approved_at: null,
    work_item: { id: ITEM.id, source_key: ITEM.source_key, title: ITEM.title, project_id: "p1", work_state: "planning", source_url: null },
  });
  const counts = () => plans.reduce((acc, plan) => ({ ...acc, [plan.status]: (acc[plan.status] ?? 0) + 1 }), { ready_for_review: 0 });
  return {
    plans, calls,
    planListApi: {
      loadChangePlanSummaries: async (query) => {
        calls.list.push(query);
        const rows = plans.filter((plan) => (query.queue === "review" ? plan.status === "ready_for_review"
          : !query.statuses?.length || query.statuses.includes(plan.status)));
        return { items: rows.map(summaryOf), next_cursor: null, status_counts: counts() };
      },
      loadWorkItem: async () => { calls.item += 1; return ITEM; },
    },
    workApi: {
      loadWorkItems: async () => [], loadWorkflows: async () => [],
      loadRepositoryProfiles: async () => [], loadEngineeringProfiles: async () => [], loadTechnologyBaselines: async () => [],
      loadWorkItemChangeUnits: async () => [], loadWorkItemLifecycle: async () => null,
      loadWorkItemChangePlans: async () => plans.map((plan) => ({ ...plan })),
      decideWorkChangePlan: async (args) => {
        calls.decide.push(args);
        if (failDecision) throw new Error("acceptance_coverage_incomplete");
        const plan = plans.find((entry) => entry.id === args.changePlanId);
        plan.status = args.action === "approve" ? "approved" : args.action === "reject" ? "rejected" : "needs_clarification";
        plan.decided_at = "2026-10-01T13:00:00";
        return {};
      },
      generateWorkItemLlmWorkPlan: async () => { calls.generate += 1; return { id: "plan-v3" }; },
    },
  };
}

function renderWorkArea(backend, search) {
  globalThis.window = fakeWindow(search);
  const loadModule = makeLoader({
    "/workApi": backend.workApi, "/workChangePlanApi": backend.workApi, "/workCodingApi": backend.workApi,
    "/workPlanListApi": backend.planListApi,
    "/PageHelpButton": { PageHelpButton: () => null },
    "/WorkJiraWriteback": { WorkJiraWriteback: Null },
    "/WorkIntakePage": { WorkIntakePage: Null },
    "/WorkReviewerRecommendations": { WorkReviewerRecommendations: Null },
  });
  const { WorkAreaWorkspace } = loadModule("WorkAreaWorkspace.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkAreaWorkspace, { projects: [] })); });
  return view;
}

const queueRows = (root) => root.findAll((node) => node.type === "tr" && node.props["aria-selected"] !== undefined);
const detail = (root) => root.find((node) => node.type === "div" && node.props["data-testid"] === "work-item-detail");

test("deciding an older plan from Plans → Waiting for review updates the detail and the queue without Refresh", async () => {
  const backend = fakeBackend();
  const view = renderWorkArea(backend, "?area=work&work_item_id=item-far&change_plan_id=plan-v1");
  await flush();
  act(() => buttons(view.root, /^Waiting for review/)[0].props.onClick());
  await flush();
  assert.equal(queueRows(view.root).length, 2);
  assert.match(text(view.root.findByProps({ "data-testid": "plan-review-demand" })), /^2 Change Plans are waiting/);
  assert.equal(backend.calls.item, 1, "the item outside the loaded list was read by id");

  // The chosen plan is the first section under the item heading, mounted once.
  const sections = detail(view.root).findAll((node) => node.type === "section").map((node) => text(node.findByType("h3")));
  assert.equal(sections[0], "Selected Change Plan");
  assert.equal(sections.filter((title) => /Change Plan/.test(title)).length, 1);
  assert.ok(sections.indexOf("Request") > 0, "the Work Item context follows below");
  assert.match(text(detail(view.root)), /Version 1/);

  const listLoads = backend.calls.list.length;
  await act(async () => { buttons(view.root, /^Approve v1$/)[0].props.onClick(); });
  await flush();
  assert.equal(backend.calls.decide[0].changePlanId, "plan-v1");
  assert.ok(backend.calls.list.length > listLoads, "the list reloaded on its own");
  assert.deepEqual(queueRows(view.root).map((row) => text(row).includes("v2")), [true], "the decided plan left the queue");
  assert.match(text(view.root.findByProps({ "data-testid": "plan-review-demand" })), /^1 Change Plan is waiting/);
  assert.match(text(detail(view.root)), /Version 1/, "the selected id is kept");
  assert.match(text(detail(view.root)), /approved/);
  assert.equal(buttons(view.root, /^Approve v1$/).length, 0, "a decided plan offers no decision");
  assert.equal(window.location.search, "?area=work&work_item_id=item-far&change_plan_id=plan-v1&work_view=reviews",
    "the open plan and the Work page stay in the address");
  act(() => view.unmount());
  delete globalThis.window;
});

test("a failed decision keeps the list, the selection and the error", async () => {
  const backend = fakeBackend({ failDecision: true });
  const view = renderWorkArea(backend, "?area=work&work_item_id=item-far&change_plan_id=plan-v1");
  await flush();
  const listLoads = backend.calls.list.length;
  await act(async () => { buttons(view.root, /^Reject$/)[0].props.onClick(); });
  await flush();
  assert.equal(backend.calls.list.length, listLoads, "no reload after a failed mutation");
  assert.match(text(detail(view.root)), /acceptance_coverage_incomplete/);
  assert.match(text(detail(view.root)), /Version 1/);
  assert.equal(buttons(view.root, /^Approve v1$/).length, 1, "the plan is still decidable");
  act(() => view.unmount());
  delete globalThis.window;
});

// ---- WorkChangePlans on its own: exclusive mutations and load races ----------------------------

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function loadChangePlans(workApi) {
  globalThis.window = fakeWindow("");
  const loadModule = makeLoader({ "/workApi": workApi, "/workChangePlanApi": workApi, "/workCodingApi": workApi });
  return loadModule("WorkChangePlans.tsx").WorkChangePlans;
}

test("while a decision is pending no other mutation or version switch can start", async () => {
  const backend = fakeBackend();
  const pending = deferred();
  const Plans = loadChangePlans({ ...backend.workApi, decideWorkChangePlan: async (args) => { backend.calls.decide.push(args); await pending.promise; return {}; } });
  let view;
  act(() => { view = TestRenderer.create(createElement(Plans, { item: ITEM, workflows: [], focusPlanId: "plan-v1", onSelectPlan: () => {} })); });
  await flush();
  act(() => { buttons(view.root, /^Approve v1$/)[0].props.onClick(); });
  for (const label of [/^New version$/, /^Reject$/, /^Clarify$/, /^v2 · /, /^v1 · /]) {
    assert.equal(buttons(view.root, label)[0].props.disabled, true, String(label));
  }
  act(() => { buttons(view.root, /^Reject$/)[0].props.onClick(); });
  act(() => { buttons(view.root, /^New version$/)[0].props.onClick(); });
  assert.equal(backend.calls.decide.length, 1, "a second decision did not start");
  assert.equal(backend.calls.generate, 0, "no generation during a decision");
  await act(async () => { pending.resolve(); });
  await flush();
  assert.equal(buttons(view.root, /^New version$/)[0].props.disabled, false);
  act(() => view.unmount());
  delete globalThis.window;
});

test("a slow plan load of the previous item never replaces the current item's plans", async () => {
  const loads = { "item-a": deferred(), "item-b": deferred() };
  const decided = [];
  const Plans = loadChangePlans({
    ...fakeBackend().workApi,
    loadWorkItemChangePlans: (itemId) => loads[itemId].promise,
    decideWorkChangePlan: async (args) => { decided.push(args.changePlanId); return {}; },
  });
  const plan = (id, itemId) => ({ ...fullPlan(id, 1, "ready_for_review"), work_item_id: itemId, understood_request: `Request of ${id}` });
  let view;
  act(() => { view = TestRenderer.create(createElement(Plans, { item: { ...ITEM, id: "item-a" }, workflows: [] })); });
  act(() => view.update(createElement(Plans, { item: { ...ITEM, id: "item-b" }, workflows: [] })));
  await act(async () => { loads["item-b"].resolve([plan("plan-b1", "item-b")]); });
  await act(async () => { loads["item-a"].resolve([plan("plan-a1", "item-a")]); });
  await flush();
  assert.match(text(view.root), /Request of plan-b1/);
  assert.doesNotMatch(text(view.root), /plan-a1/);
  await act(async () => { buttons(view.root, /^Approve v1$/)[0].props.onClick(); });
  assert.deepEqual(decided, ["plan-b1"], "the decision targets the current item's plan");
  act(() => view.unmount());
  delete globalThis.window;
});
