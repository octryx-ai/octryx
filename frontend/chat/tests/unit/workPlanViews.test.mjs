// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workPlanViews.test.mjs
//
// Change Plans and Plan reviews: the lists read real plans from the backend contract; the
// review queue is the backend's `queue=review`; a row opens and decides its exact plan id, never
// the newest version by accident; an unknown plan id is an explicit error with no decision.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/chat/work/workPlanListModel.ts";
import * as planStatus from "../../src/chat/work/planStatus.ts";
import * as planApi from "../../src/chat/work/workPlanListApi.ts";
import * as workUtils from "../../src/chat/work/workUtils.ts";
import * as clarificationModel from "../../src/chat/work/workPlanClarificationModel.ts";
import * as planLabels from "../../src/chat/work/workChangePlanLabels.ts";
import * as detailLink from "../../src/chat/work/workDetailLink.ts";
import { useWorkItemSelection } from "../../src/chat/work/useWorkItemSelection.ts";
import * as loadingState from "../../src/layout/LoadingState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const buttons = (root, pattern) => root.findAll((node) => node.type === "button" && pattern.test(text(node)));
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const Badge = ({ value }) => createElement("span", { className: "work-badge" }, String(value).replaceAll("_", " "));

function loadComponent(path, exportName, stubs) {
  const source = fs.readFileSync(new URL(`../../src/chat/work/${path}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(output, {
    exports,
    window: globalThis.window,
    require: (name) => {
      if (name.endsWith(".css")) return {};
      if (name.endsWith("/layout/LoadingState")) return loadingState;
      const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
      return stub ? stub[1] : require(name);
    },
  });
  return exports[exportName];
}

function summary(id, version, status, extra = {}) {
  return {
    id, work_item_id: extra.work_item_id ?? "item-1", version, status, title: `Plan ${id}`, workflow_id: null,
    supersedes_plan_id: null, plan_type: extra.plan_type ?? null, open_questions_count: extra.open_questions_count ?? 0,
    acceptance_criteria_count: 0, change_unit_count: 0, created_by: "u1", created_by_name: "Ada Planner", decided_by: null,
    created_at: "2026-10-01T12:00:00", updated_at: "2026-10-01T12:00:00", decided_at: extra.decided_at ?? null, approved_at: null,
    work_item: { id: extra.work_item_id ?? "item-1", source_key: extra.key ?? "SHOP-1", title: "Item SHOP-1", project_id: "p1", work_state: "planning", source_url: null },
  };
}

// ---- pure contract helpers -------------------------------------------------------------------

test("the review view asks the backend queue; the plan view sends explicit status and history filters", () => {
  assert.deepEqual(model.planListQuery("reviews", { status: "approved", showSuperseded: true }), { queue: "review", cursor: undefined });
  assert.deepEqual(model.planListQuery("plans", model.DEFAULT_PLAN_LIST_FILTER), { statuses: [], includeSuperseded: false, cursor: undefined });
  assert.deepEqual(model.planListQuery("plans", { status: "superseded", showSuperseded: false }, "c1"),
    { statuses: [], includeSuperseded: false, cursor: "c1" }, "never sends the 422 contradiction");
  assert.equal(planApi.changePlanListUrl({ queue: "review" }), "/api/v1/secure-work/change-plans?queue=review&limit=50");
  assert.equal(planApi.changePlanListUrl({ statuses: ["approved"], includeSuperseded: true, cursor: "abc", limit: 10 }),
    "/api/v1/secure-work/change-plans?status=approved&include_superseded=true&limit=10&cursor=abc");
});

test("status chips come from the response counts, unknown statuses verbatim, review demand from ready_for_review", () => {
  const chips = model.planStatusChips({ approved: 2, ready_for_review: 3, legacy_hold: 1, needs_clarification: 0 });
  assert.deepEqual(chips.map((chip) => chip.status), ["ready_for_review", "needs_clarification", "approved", "legacy_hold"]);
  assert.equal(chips.at(-1).label, "legacy hold");
  assert.match(planStatus.planStatusLabel("needs_clarification"), /waiting on author/);
  assert.equal(model.planTotal({ approved: 2, ready_for_review: 3 }), 5);
  assert.equal(model.reviewDemandText({ ready_for_review: 1, needs_clarification: 4 }), "1 Change Plan is waiting for a reviewer decision.");
  assert.equal(model.planListEmptyState("reviews", model.DEFAULT_PLAN_LIST_FILTER).body, "Plans appear here when they are ready for a reviewer's decision.");
  assert.deepEqual(model.planListEmptyState("plans", model.DEFAULT_PLAN_LIST_FILTER),
    { title: "No plans yet.", body: "Plans are created from a work item.", openWorkItems: true }, "one sentence and the way to the board");
});

// ---- the list component ----------------------------------------------------------------------

function loadPlanList() {
  return loadComponent("WorkPlanList.tsx", "WorkPlanList", {
    "/WorkAreaViews": { Badge },
    "/workPlanListApi": { loadChangePlanSummaries: async () => { throw new Error("injected loader expected"); } },
    "/workPlanListModel": model,
    "/planStatus": planStatus,
    "/workUtils": workUtils,
  });
}

test("a Change Plans row opens its exact plan, including an older version of the same item", async () => {
  const List = loadPlanList();
  const queries = [];
  const pages = {
    first: { items: [summary("plan-v2", 2, "ready_for_review"), summary("plan-v1", 1, "approved", { decided_at: "2026-10-01T13:00:00", plan_type: "coding_change" })],
      next_cursor: "cursor-2", status_counts: { approved: 1, ready_for_review: 1, draft: 0 } },
    second: { items: [summary("plan-v1", 1, "approved"), summary("plan-other", 1, "draft", { work_item_id: "item-2", key: "OPS-9" })],
      next_cursor: null, status_counts: { approved: 1, ready_for_review: 1, draft: 1 } },
  };
  const load = async (query) => { queries.push(query); return query.cursor ? pages.second : pages.first; };
  const opened = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(List, { mode: "plans", reloadKey: 0, selectedPlanId: "plan-v1", onOpenPlan: (row) => opened.push(row), load })); });
  await flush();
  assert.deepEqual(queries[0], { statuses: [], includeSuperseded: false, cursor: undefined });
  const header = view.root.findAllByType("th").map(text);
  assert.deepEqual(header, ["Work item", "Plan", "Status", "Type", "Created by", "Updated", "Decided", "Detail"]);
  const rows = view.root.findAllByType("tr").slice(1);
  assert.equal(rows.length, 2);
  assert.equal(rows[1].props["aria-selected"], true, "the open plan is marked");
  assert.match(text(rows[1]), /v1/);
  assert.match(text(rows[1]), /coding change/);
  assert.match(text(rows[0]), /Not recorded/, "a missing plan type is not guessed");

  act(() => buttons(rows[1], /^Open$/)[0].props.onClick());
  assert.equal(opened[0].id, "plan-v1");
  assert.equal(opened[0].version, 1);

  await act(async () => { buttons(view.root, /^Load more$/)[0].props.onClick(); });
  assert.equal(queries[1].cursor, "cursor-2");
  const ids = view.root.findAllByType("tr").slice(1).map((row) => text(row));
  assert.equal(ids.length, 3, "a repeated row is not duplicated");
  assert.equal(buttons(view.root, /^Load more$/).length, 0);
  act(() => view.unmount());
});

test("status chips and the superseded toggle send explicit filters; a failure is shown, not an empty list", async () => {
  const List = loadPlanList();
  const queries = [];
  let fail = false;
  const load = async (query) => {
    queries.push(query);
    if (fail) throw new Error("Workspace is outside your Work access");
    return { items: [], next_cursor: null, status_counts: counts };
  };
  let counts = { approved: 0, ready_for_review: 0 };
  const openedBoard = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(List, { mode: "plans", reloadKey: 0, selectedPlanId: null, onOpenPlan: () => {},
    onOpenWorkItems: () => openedBoard.push(true), load })); });
  await flush();
  assert.match(text(view.root), /No plans yet\.Plans are created from a work item\./);
  assert.equal(buttons(view.root, /^Approved · 0$/).length, 0, "m3: no status filters while there are no plans");
  act(() => buttons(view.root, /^Open work items$/)[0].props.onClick());
  assert.equal(openedBoard.length, 1);

  counts = { approved: 0, ready_for_review: 2 };
  act(() => view.update(createElement(List, { mode: "plans", reloadKey: 2, selectedPlanId: null, onOpenPlan: () => {}, load })));
  await flush();
  act(() => buttons(view.root, /^Approved · 0$/)[0].props.onClick());
  await flush();
  assert.deepEqual(queries.at(-1), { statuses: ["approved"], includeSuperseded: false, cursor: undefined });
  assert.match(text(view.root), /No Change Plans with status “Approved”/);
  act(() => view.root.findByType("input").props.onChange());
  await flush();
  assert.equal(queries.at(-1).includeSuperseded, true);

  fail = true;
  act(() => view.update(createElement(List, { mode: "plans", reloadKey: 1, selectedPlanId: null, onOpenPlan: () => {}, load })));
  await flush();
  assert.equal(text(view.root.findByProps({ role: "alert" })), "Workspace is outside your Work access");
  assert.doesNotMatch(text(view.root), /No Change Plans|No plans yet/, "an error is not presented as an empty list");
  act(() => view.unmount());
});

test("Plan reviews query only the backend queue and label its count as review demand", async () => {
  const List = loadPlanList();
  const queries = [];
  const load = async (query) => {
    queries.push(query);
    return { items: [summary("plan-r", 3, "ready_for_review")], next_cursor: null, status_counts: { ready_for_review: 1, needs_clarification: 5, approved: 9 } };
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(List, { mode: "reviews", reloadKey: 0, selectedPlanId: null, onOpenPlan: () => {}, load })); });
  await flush();
  assert.deepEqual(queries, [{ queue: "review", cursor: undefined }]);
  assert.equal(text(view.root.findByProps({ "data-testid": "plan-review-demand" })), "1 Change Plan is waiting for a reviewer decision.");
  assert.equal(view.root.findAll((node) => node.props?.["aria-pressed"] !== undefined).length, 0, "no status chips in the queue");
  act(() => view.unmount());
});

// ---- the plan detail: exact id drives version and decision -----------------------------------

function fullPlan(id, version, status) {
  return {
    id, work_item_id: "item-1", workflow_id: null, supersedes_plan_id: null, version, status, title: `Plan ${id}`,
    understood_request: `Request of ${id}`, assumptions: [], open_questions: [], affected_repositories: [], change_units: [],
    proposed_branches: [], planned_files: [], validation_plan: [], security_risks: [], reviewer_recommendations: [],
    required_approvals: [], expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {}, jira_sync_preview: {},
    created_by: "u1", created_at: "2026-10-01T12:00:00", updated_at: "2026-10-01T12:00:00",
  };
}

function loadChangePlans(plans, calls) {
  return loadComponent("WorkChangePlans.tsx", "WorkChangePlans", {
    "/workChangePlanApi": {
      loadWorkItemChangePlans: async () => plans,
      decideWorkChangePlan: async (args) => { calls.push(args); return {}; },
      generateWorkItemLlmWorkPlan: async () => ({ id: "plan-new" }),
    },
    "/workPlanListModel": model,
    "/planStatus": planStatus,
    "/workUtils": workUtils,
    // The real view of the selected plan, with the real answers component; it renders the plan's open questions.
    "/WorkChangePlanView": { WorkChangePlanView: loadComponent("WorkChangePlanView.tsx", "WorkChangePlanView", {
      "/WorkAreaViews": { Badge },
      "/WorkPlanClarificationAnswers": { WorkPlanClarificationAnswers: loadComponent("WorkPlanClarificationAnswers.tsx",
        "WorkPlanClarificationAnswers", { "/workPlanClarificationModel": clarificationModel, "/workUtils": workUtils }) },
      "/WorkChangePlanBlocks": Object.fromEntries(["PlanBlock", "StringList", "CompactObjects", "VersionDelta"].map((name) =>
        [name, loadComponent("WorkChangePlanBlocks.tsx", name, { "/workChangePlanLabels": planLabels })])),
      "/workChangePlanLabels": planLabels,
    }) },
  });
}

const item = { id: "item-1", source_key: "SHOP-1", title: "Item" };
const plans = [fullPlan("plan-v3", 3, "ready_for_review"), fullPlan("plan-v2", 2, "needs_clarification"), fullPlan("plan-v1", 1, "approved")];

test("a focused older plan is shown and decided by its own id, not the newest version", async () => {
  const calls = [];
  const Plans = loadChangePlans(plans, calls);
  const selected = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(Plans, { item, workflows: [], focusPlanId: "plan-v2", onSelectPlan: (id) => selected.push(id) })); });
  await flush();
  assert.match(text(view.root), /Version 2/);
  assert.match(text(view.root), /newest is v3/);
  assert.match(text(view.root), /Request of plan-v2/);
  assert.doesNotMatch(text(view.root), /Request of plan-v3/);
  await act(async () => { buttons(view.root, /^Approve v2$/)[0].props.onClick(); });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].changePlanId, "plan-v2");
  assert.equal(calls[0].action, "approve");

  act(() => buttons(view.root, /^v1 · approved$/)[0].props.onClick());
  assert.deepEqual(selected, ["plan-v1"], "choosing a version goes through the address, by id");
  act(() => view.unmount());
});

test("an unknown or foreign plan id is an explicit error with no decision and no fallback", async () => {
  const calls = [];
  const Plans = loadChangePlans(plans, calls);
  let view;
  act(() => { view = TestRenderer.create(createElement(Plans, { item, workflows: [], focusPlanId: "plan-of-another-item", onSelectPlan: () => {} })); });
  await flush();
  assert.ok(view.root.findByProps({ "data-testid": "change-plan-focus-missing" }));
  assert.match(text(view.root), /Requested plan not found/);
  assert.equal(buttons(view.root, /^Approve/).length, 0);
  assert.equal(buttons(view.root, /^Reject$/).length, 0);
  assert.doesNotMatch(text(view.root), /Request of plan-v3/, "the newest plan is not shown in its place");
  assert.equal(buttons(view.root, /^v\d · /).length, 3, "the versions stay available to choose explicitly");
  assert.equal(calls.length, 0);
  act(() => view.unmount());
});

test("without a requested id the newest plan is shown; a final plan offers no decision", async () => {
  const calls = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(loadChangePlans(plans, calls), { item, workflows: [] })); });
  await flush();
  assert.match(text(view.root), /Version 3/);
  assert.equal(buttons(view.root, /^Approve v3$/).length, 1);
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(loadChangePlans(plans, calls), { item, workflows: [], focusPlanId: "plan-v1" })); });
  await flush();
  assert.match(text(view.root), /Version 1/);
  assert.equal(buttons(view.root, /^Approve/).length, 0, "an approved plan is final");
  act(() => view.unmount());
});

// ---- the full Work Item behind a selection ---------------------------------------------------

test("an item outside the loaded list is read by id; a failure is reported, a summary is never used", async () => {
  const loads = [];
  const full = { id: "item-far", source_key: "SHOP-1500", title: "Far item", description: "full" };
  let result;
  function Probe({ id, items, load }) {
    result = useWorkItemSelection(id, items, 0, load);
    return null;
  }
  const okLoad = async (id) => { loads.push(id); return full; };
  let view;
  act(() => { view = TestRenderer.create(createElement(Probe, { id: "item-far", items: [], load: okLoad })); });
  assert.equal(result.loading, true);
  await flush();
  assert.deepEqual(loads, ["item-far"]);
  assert.equal(result.item, full);

  const listed = { id: "item-near", source_key: "SHOP-2" };
  act(() => view.update(createElement(Probe, { id: "item-near", items: [listed], load: okLoad })));
  assert.equal(result.item, listed);
  assert.deepEqual(loads, ["item-far"], "a listed item is not fetched");

  const failLoad = async () => { throw new Error("Work Item is outside your workspace access"); };
  act(() => view.update(createElement(Probe, { id: "item-denied", items: [], load: failLoad })));
  await flush();
  assert.equal(result.item, null);
  assert.equal(result.error, "Work Item is outside your workspace access");
  act(() => view.unmount());
});

test("the detail address keeps the work item and the exact plan id, and clears both on close", () => {
  const history = [];
  globalThis.window = {
    location: { href: "https://octryx.example/chat?area=work&work_item_id=old", search: "?area=work&work_item_id=old" },
    history: { replaceState: (_state, _title, url) => history.push(url) },
  };
  assert.equal(detailLink.readWorkDetailParam("work_item_id"), "old");
  detailLink.writeWorkDetailLink("item-1", "plan-v2");
  assert.equal(history.at(-1), "https://octryx.example/chat?area=work&work_item_id=item-1&change_plan_id=plan-v2");
  detailLink.writeWorkDetailLink(null, null);
  assert.equal(history.at(-1), "https://octryx.example/chat?area=work");
  delete globalThis.window;
});
