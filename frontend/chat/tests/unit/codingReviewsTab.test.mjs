// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingReviewsTab.test.mjs
//
// The real Coding session detail (live navigation correction): the review decision is in the
// Reviews tab — once — even without planned files; Changes keeps file feedback and points to Reviews.
// Review events are loaded by the Reviews tab itself, with error and retry, and survive a reload.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { buildCodingSessionSummary } from "../../src/chat/coding/codingSessionModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const flush = () => act(async () => { for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); });
const Null = () => null;

// A small review-event backend: decisions get the server record, including the reviewer label.
function fakeBackend({ failFirstLoad = false } = {}) {
  const state = { events: [], loads: 0, posts: [] };
  return {
    state,
    api: {
      loadCodingReviewEvents: async (workItemId) => {
        state.loads += 1;
        if (failFirstLoad && state.loads === 1) throw new Error("Review events are temporarily unavailable");
        return { items: state.events.filter((event) => event.work_item_id === workItemId), agent_feedback_context: null };
      },
      createCodingReviewEvent: async (workItemId, payload) => {
        state.posts.push(JSON.parse(JSON.stringify(payload)));
        const event = {
          id: `event-${state.posts.length}`, work_item_id: workItemId, event_type: payload.event_type, status: payload.decision,
          file_path: "", body: payload.body, created_at: `2026-10-04T12:00:0${state.posts.length}`, created_by: "user-alice",
          metadata: { review_decision_record: { decision: payload.decision, change_plan_id: payload.change_plan_id,
            change_unit_id: payload.change_unit_id, actor_label: "Alice Reviewer" } },
          agent_context: {},
        };
        state.events.push(event);
        return event;
      },
    },
  };
}

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name === suffix || name.endsWith(suffix));
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
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, URL, URLSearchParams, Intl, console,
      require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

function loadDetail(backend) {
  const loadModule = makeLoader({
    "/work/workApi": backend.api, "/work/workChangePlanApi": backend.api, "/work/workCodingApi": backend.api,
    "@monaco-editor/react": { Editor: Null, DiffEditor: Null },
    "/CodingAuditPanel": { CodingAuditPanel: Null },
    "/CodingPipelineTracePanel": { CodingPipelineTracePanel: Null },
    "/CodingRuntimeObservability": { RuntimeObservabilityDeepDive: Null, RuntimeObservabilitySummary: Null },
    "/CodingWorkspaceEvidence": { CodingWorkspaceEvidence: Null },
  });
  return loadModule("CodingSessionDetail.tsx").CodingSessionDetail;
}

const ITEM = { id: "ops-2", source_key: "OPS-2", title: "Synthetic item", description: "", source_status: "Open", work_state: "planning",
  sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [], source_fields: {}, source_url: null };
const PLAN = {
  id: "plan-2", work_item_id: "ops-2", version: 2, status: "approved", title: "Plan v2", understood_request: "", assumptions: [],
  open_questions: [], affected_repositories: [], change_units: [], proposed_branches: [], planned_files: [], validation_plan: [],
  security_risks: [], reviewer_recommendations: [{ display_name: "Recommended Rita", score: 0.9 }], required_approvals: [],
  expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {}, jira_sync_preview: {}, created_by: "u1",
};
// No planned files anywhere: the unit has no expected paths.
const UNIT = { id: "unit-a", work_item_id: "ops-2", repository_name: "ops-repo", branch_name: "feature/ops-2", scope: "",
  expected_paths: [], validation_commands: [], reviewer_policy: {}, dependency_order: 0, status: "planned",
  updated_at: "2026-10-04T10:00:00.123456" };

function detailFor() {
  return { workItem: ITEM, changePlans: [PLAN], changeUnits: [UNIT], reviewerPayload: null, stateEvents: [], pipelineTrace: null,
    reviewEventsPayload: { items: [] }, auditReport: null, cicdPipelineTraces: null, cicdFindings: null,
    observability: null };
}

function renderDetail(Detail, activeTab, onTabChange = () => {}) {
  const session = buildCodingSessionSummary({ item: ITEM, changePlans: [PLAN], changeUnits: [UNIT] });
  let view;
  act(() => {
    view = TestRenderer.create(createElement(Detail, {
      session, detail: detailFor(), loading: false, activeTab, startingAgent: false, onTabChange,
      onStartAgent: () => {}, onRestartAgent: () => {},
    }));
  });
  return view;
}

const decisionForms = (root) => root.findAll((node) => node.props?.["aria-label"] === "Review decision");
const select = (root, index) => decisionForms(root)[0].findAll((node) => node.type === "select")[index];
const button = (root, label) => root.find((node) => node.type === "button" && text(node) === label);

test("the Reviews tab records a decision without planned files, and it is still there after a reload", async () => {
  const backend = fakeBackend();
  const Detail = loadDetail(backend);
  let view = renderDetail(Detail, "reviews");
  await flush();
  assert.equal(backend.state.loads, 1, "the Reviews tab loads its own review events");
  assert.equal(decisionForms(view.root).length, 1, "exactly one decision form");
  const page = text(view.root);
  assert.doesNotMatch(page, /separate from Work Plan approval/, "the explanation lives in the help");
  assert.match(page, /Recommended Rita/, "recommendations stay below the decision");
  assert.ok(page.indexOf("Review decision") < page.indexOf("Reviewer recommendations"), "the decision comes first");

  assert.match(text(select(view.root, 0)), /Change Unit ops-repo · feature\/ops-2/);
  act(() => select(view.root, 1).props.onChange({ target: { value: "approved" } }));
  await act(async () => { await button(view.root, "Record decision").props.onClick(); });
  assert.deepEqual(backend.state.posts, [{
    event_type: "review_decision", decision: "approved", change_plan_id: "plan-2", expected_plan_version: 2,
    change_unit_id: "unit-a", expected_change_unit_marker: "2026-10-04T10:00:00.123456", file_path: "", body: "",
    metadata: { source: "coding_review_decision_panel" },
  }]);
  assert.match(text(view.root.findByProps({ "aria-label": "Recorded review decisions" })), /Alice Reviewer · Approve · Change Unit ops-repo/);
  act(() => view.unmount());

  view = renderDetail(Detail, "reviews");
  await flush();
  assert.match(text(view.root.findByProps({ "aria-label": "Recorded review decisions" })), /Alice Reviewer · Approve/,
    "a reload shows the recorded decision from the server");
  act(() => view.unmount());
});

test("a failed load is shown with a retry, and no decision form is offered until events are loaded", async () => {
  const backend = fakeBackend({ failFirstLoad: true });
  const view = renderDetail(loadDetail(backend), "reviews");
  await flush();
  assert.match(text(view.root.findByProps({ role: "alert" })), /temporarily unavailable/);
  assert.equal(decisionForms(view.root).length, 0);
  await act(async () => { await button(view.root, "Retry").props.onClick(); });
  await flush();
  assert.equal(decisionForms(view.root).length, 1);
  act(() => view.unmount());
});

test("the Changes tab keeps file feedback only and opens Reviews for the decision", async () => {
  const backend = fakeBackend();
  const tabs = [];
  const view = renderDetail(loadDetail(backend), "changes", (tab) => tabs.push(tab));
  await flush();
  assert.equal(decisionForms(view.root).length, 0, "no second decision surface");
  assert.match(text(view.root), /File comments need a planned file. A review decision needs none./);
  act(() => button(view.root, "Open Reviews").props.onClick());
  assert.deepEqual(tabs, ["reviews"]);
  assert.equal(backend.state.loads, 0, "Changes does not load the decision events");
  act(() => view.unmount());
});
