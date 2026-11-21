// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingSessionSteps.test.mjs
//
// A Coding session reads as steps (Plan → Changes → Tests → Pull request → Review → Done). Step
// states come from recorded evidence only; the header has one primary next action; the step the session stands at
// opens by itself, finished ones stay closed; loading ends in an explicit state; Restart sits last in ⋯, confirmed
// by the session's name.
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
import { codingValidationEvidence } from "../../src/chat/coding/codingEvidenceModel.ts";
import {
  codingNextAction,
  codingSessionSteps,
  currentStepKey,
  sectionForTab,
  startBlockedReason,
} from "../../src/chat/coding/codingSessionSteps.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const Null = () => null;

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
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, get window() { return globalThis.window; }, get document() { return globalThis.document; }, URL, URLSearchParams, Intl, console,
      require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

const ITEM = { id: "ops-7", source_key: "OPS-7", title: "Rotate the token", description: "", source_status: "Open", work_state: "planning",
  sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [], source_fields: {}, source_url: null };
const plan = (overrides = {}) => ({
  id: "plan-1", work_item_id: "ops-7", version: 1, status: "approved", title: "Plan v1", understood_request: "", assumptions: [],
  open_questions: [], affected_repositories: [], change_units: [], proposed_branches: [], planned_files: [{ path: "a.py" }, { path: "b.py" }],
  validation_plan: [], security_risks: [], reviewer_recommendations: [], required_approvals: [], expected_prs: [], rollback_plan: "",
  trace_refs: [], evidence: {}, jira_sync_preview: {}, created_by: "u1", approved_at: "2026-11-05T09:00:00Z", ...overrides,
});
const UNIT = { id: "unit-a", work_item_id: "ops-7", repository_name: "ops-repo", branch_name: "feature/ops-7", scope: "",
  expected_paths: [], validation_commands: [], reviewer_policy: {}, dependency_order: 0, status: "planned" };
const AGENT = { id: "chat-1", status: "active", run_status: "running", agent_type: "coding", chat_url: "/chat?session_id=chat-1",
  started_at: "2026-11-05T10:00:00Z" };

function detailFor({ plans = [plan()], units = [UNIT] } = {}) {
  return { workItem: ITEM, changePlans: plans, changeUnits: units, reviewerPayload: null, stateEvents: [], pipelineTrace: null,
    reviewEventsPayload: { items: [] }, auditReport: null, cicdPipelineTraces: null, cicdFindings: null, observability: null };
}

function sessionFor({ state = "approved", plans = [plan()], units = [UNIT], agentSessions = [], pullRequestUrls = [], sourceFields = {} } = {}) {
  const base = buildCodingSessionSummary({ item: { ...ITEM, source_fields: sourceFields }, changePlans: plans, changeUnits: units,
    agentSessions, pullRequestUrls });
  return { ...base, state, latestAgentSession: agentSessions[0] || null };
}

function stepsFor(session, detail = detailFor(), latestPlan = detail.changePlans[0] || null) {
  const validation = codingValidationEvidence(session.workItem.source_fields, latestPlan, null);
  return codingSessionSteps({ session, detail, latestPlan, validation, preparedWorkspaces: 0 });
}
const stateOf = (steps) => Object.fromEntries(steps.map((step) => [step.key, step.state]));

test("steps map recorded evidence: an approved plan is done, a running agent makes Changes the current step", () => {
  const session = sessionFor({ state: "implementing", agentSessions: [AGENT] });
  const steps = stepsFor(session);
  assert.deepEqual(steps.map((step) => step.title), ["Plan", "Changes", "Tests", "Pull request", "Review", "Done"]);
  assert.deepEqual(stateOf(steps), { plan: "done", changes: "active", tests: "pending", pullRequest: "pending", review: "pending", done: "pending" });
  assert.match(steps[0].summary, /^Plan v1 · Approved · 2 files planned$/);
  assert.equal(steps[0].at, "2026-11-05T09:00:00Z");
  assert.match(steps[1].summary, /1 change unit in ops-repo · agent running\./);
  assert.equal(currentStepKey(steps), "changes");
});

test("a plan with open questions is a problem; failed validation is a problem; a linked PR completes Changes", () => {
  const questions = sessionFor({ state: "planned", plans: [plan({ status: "needs_clarification", approved_at: null })] });
  const questionSteps = stepsFor(questions, detailFor({ plans: [plan({ status: "needs_clarification" })] }));
  assert.equal(stateOf(questionSteps).plan, "problem");
  assert.equal(currentStepKey(questionSteps), "plan");

  const failing = sessionFor({ state: "testing", sourceFields: { validation_results: [{ command: "pytest", status: "failed" }] },
    pullRequestUrls: ["https://git.example/projects/OPS/repos/ops/pull-requests/12"] });
  const steps = stepsFor(failing);
  assert.equal(stateOf(steps).tests, "problem");
  assert.equal(stateOf(steps).changes, "done", "a linked pull request is the recorded end of Changes");
  assert.equal(stateOf(steps).pullRequest, "done");
  assert.match(steps.find((step) => step.key === "pullRequest").summary, /PR 12 opened\./);
  assert.equal(currentStepKey(steps), "tests");
});

test("a planned check alone never completes Tests, and the Done step follows the source state only", () => {
  const planned = sessionFor({ state: "testing" });
  const steps = stepsFor(planned, detailFor({ plans: [plan({ validation_plan: [{ name: "pytest" }] })] }));
  assert.equal(stateOf(steps).tests, "active");
  assert.match(steps.find((step) => step.key === "tests").summary, /No validation results recorded · 1 check planned/);
  assert.equal(stateOf(stepsFor(sessionFor({ state: "completed" }))).done, "done");
  assert.equal(stateOf(stepsFor(sessionFor({ state: "cancelled" }))).done, "problem");
});

test("each tab opens the step or section that holds its content; overview opens the current step", () => {
  const steps = stepsFor(sessionFor({ state: "implementing", agentSessions: [AGENT] }));
  assert.equal(sectionForTab("overview", steps), "changes");
  assert.equal(sectionForTab("reviews", steps), "review");
  assert.equal(sectionForTab("tests", steps), "tests");
  assert.equal(sectionForTab("policy", steps), "rules");
  assert.equal(sectionForTab("process", steps), "details");
});

test("next action: start once approved, follow a running agent, open the PR or review, nothing while Work must act", () => {
  assert.deepEqual(codingNextAction(sessionFor({ state: "approved" }), true), { kind: "start" });
  assert.deepEqual(codingNextAction(sessionFor({ state: "implementing", agentSessions: [AGENT] }), true),
    { kind: "link", label: "Open task chat", href: "/chat?session_id=chat-1" });
  const pr = "https://git.example/projects/OPS/repos/ops/pull-requests/12";
  assert.deepEqual(codingNextAction(sessionFor({ state: "pr_open", pullRequestUrls: [pr] }), false),
    { kind: "link", label: "Open pull request", href: pr, external: true });
  assert.deepEqual(codingNextAction(sessionFor({ state: "review_ready" }), false), { kind: "section", label: "Open review", section: "review" });
  assert.equal(codingNextAction(sessionFor({ state: "needs_replan" }), false), null, "the Work action panel names the place");
  assert.equal(codingNextAction(sessionFor({ state: "completed" }), false), null);
  assert.equal(startBlockedReason(sessionFor({ state: "planned" }), plan({ status: "ready_for_review" })), "Needs an approved plan.");
  assert.equal(startBlockedReason(sessionFor({ state: "blocked" }), plan()), "Resolve the work action below first.");
});

// ---- rendered --------------------------------------------------------------------------------

const loadModule = makeLoader({
  "/CodingAuditPanel": { CodingAuditPanel: Null },
  "/CodingPipelineTracePanel": { CodingPipelineTracePanel: Null },
  "/CodingRuntimeObservability": { RuntimeObservabilityDeepDive: Null, RuntimeObservabilitySummary: Null },
  "/CodingReviewWorkspace": { CodingReviewWorkspace: () => createElement("p", null, "diff view") },
  "/CodingReviewsPanel": { CodingReviewsPanel: () => createElement("p", null, "review decisions") },
  "/CodingWorkspaceEvidence": { CodingWorkspaceEvidence: Null },
  "/CodingExecutionTrace": { CodingExecutionTrace: () => createElement("p", null, "live trace") },
});

function render(props) {
  const { CodingSessionDetail } = loadModule("CodingSessionDetail.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(CodingSessionDetail, {
      loading: false, activeTab: "overview", startingAgent: false, onTabChange: () => {}, onStartAgent: () => {},
      onRestartAgent: () => {}, ...props,
    }));
  });
  return view;
}
const step = (root, key) => root.find((node) => node.props?.["data-testid"] === `coding-step-${key}`);
const head = (root, key) => step(root, key).find((node) => node.type === "button" && node.props["aria-expanded"] !== undefined);

test("rendered: the current step is open with its live output, finished and later steps stay closed", () => {
  const view = render({ session: sessionFor({ state: "implementing", agentSessions: [AGENT] }), detail: detailFor() });
  assert.equal(head(view.root, "changes").props["aria-expanded"], true);
  assert.match(text(step(view.root, "changes")), /live trace/);
  assert.match(text(step(view.root, "changes")), /diff view/);
  for (const key of ["plan", "tests", "pullRequest", "review", "done", "rules", "details"]) {
    assert.equal(head(view.root, key).props["aria-expanded"], false, `${key} is closed`);
  }
  assert.doesNotMatch(text(view.root), /review decisions/, "a closed step renders no evidence");
  assert.equal(step(view.root, "plan").props["aria-label"], "Plan: Done");
  assert.doesNotMatch(text(head(view.root, "plan")), /plan-1|unit-a/, "no ids in a step line");
  act(() => head(view.root, "plan").props.onClick());
  assert.equal(head(view.root, "plan").props["aria-expanded"], true);
  act(() => head(view.root, "plan").props.onClick());
  assert.equal(head(view.root, "plan").props["aria-expanded"], false, "a step closes again");
  act(() => view.unmount());
});

test("rendered: one primary action in the header, ids only in Details", () => {
  const view = render({ session: sessionFor({ state: "implementing", agentSessions: [AGENT] }), detail: detailFor() });
  const header = view.root.find((node) => node.type === "header");
  const primaries = header.findAll((node) => typeof node.props?.className === "string" && node.props.className.includes("work-area__button--primary"));
  assert.equal(primaries.length, 1);
  assert.equal(text(primaries[0]), "Open task chat");
  assert.match(text(header), /OPS-7 Rotate the token/);
  assert.doesNotMatch(text(view.root), /Work item id: ops-7/);
  act(() => head(view.root, "details").props.onClick());
  assert.match(text(step(view.root, "details")), /Work item id: ops-7/);
  act(() => view.unmount());
});

test("rendered: Restart from scratch is last in ⋯ and is confirmed by the session's name", async () => {
  globalThis.window = { innerWidth: 1200, addEventListener: () => {}, removeEventListener: () => {} };
  const ownDocument = globalThis.document;
  globalThis.document = { addEventListener: () => {}, removeEventListener: () => {} };
  const restarted = [];
  const view = render({ session: sessionFor({ state: "implementing", agentSessions: [AGENT] }), detail: detailFor(),
    onRestartAgent: () => restarted.push(true) });
  const menu = view.root.find((node) => node.props?.["aria-label"] === "More actions for OPS-7");
  act(() => menu.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 0, right: 0 }) } }));
  const item = view.root.find((node) => node.type === "button" && text(node) === "Restart from scratch");
  act(() => item.props.onClick());
  assert.match(text(view.root), /Restart OPS-7 from scratch\?/);
  assert.equal(restarted.length, 0, "nothing restarts before the confirmation");
  const confirm = view.root.find((node) => node.type === "button" && text(node) === "Restart OPS-7");
  await act(async () => { confirm.props.onClick(); });
  assert.equal(restarted.length, 1);
  assert.match(text(view.root), /OPS-7 restarts from scratch\./);
  act(() => view.unmount());
  delete globalThis.window;
  globalThis.document = ownDocument;
});

test("rendered: loading shows the shared outline; missing evidence ends in a plain state with Try again", () => {
  const session = sessionFor({ state: "approved" });
  const loading = render({ session, detail: null, loading: true });
  assert.equal(loading.root.findAll((node) => node.props?.["aria-label"] === "Coding session steps").length, 0);
  assert.doesNotMatch(text(loading.root), /Loading session evidence\.\.\./);
  act(() => loading.unmount());

  const retries = [];
  const missing = render({ session, detail: null, loading: false, onRetryDetail: () => retries.push(true) });
  const status = missing.root.find((node) => node.props?.className === "coding-detail__unavailable");
  assert.match(text(status), /Session evidence not available\./);
  act(() => status.findByType("button").props.onClick());
  assert.equal(retries.length, 1);
  act(() => missing.unmount());
});

test("Changes is never Done without changes; a linked PR alone says the changes are in it", () => {
  const empty = sessionFor({ state: "pr_open", units: [], pullRequestUrls: ["https://git.example/projects/OPS/repos/ops/pull-requests/12"] });
  const changes = stepsFor(empty, detailFor({ units: [] })).find((step) => step.key === "changes");
  assert.equal(changes.state, "done");
  assert.equal(changes.summary, "Changes are in the linked pull request.");
  assert.doesNotMatch(changes.summary, /No change yet/);
  const none = stepsFor(sessionFor({ state: "approved", units: [] }), detailFor({ units: [] })).find((step) => step.key === "changes");
  assert.notEqual(none.state, "done", "no change unit and no pull request is not done");
  assert.equal(none.summary, "No change yet.");
});

test("The current-action card holds no counters; counters sit in Details; Review shows only the decision", () => {
  const view = render({ session: sessionFor({ state: "implementing", agentSessions: [AGENT] }), detail: detailFor() });
  const cockpit = view.root.find((node) => node.props?.className === "coding-cockpit");
  assert.doesNotMatch(text(cockpit), /Recorded evidence|Blockers|Phase/);
  assert.equal(view.root.findAll((node) => node.props?.className === "coding-detail__counters").length, 0, "Details is closed");
  act(() => head(view.root, "details").props.onClick());
  const counters = view.root.find((node) => node.props?.className === "coding-detail__counters");
  assert.match(text(counters), /Phase.*Blockers.*Recorded evidence/);
  act(() => view.unmount());
});

// ---- UI check C4: an ended session states one outcome ------------------------------------------------
// A board showed seven COMPLETED sessions whose detail said "Current action: Resolve blockers or ask for clarification",
// "No Change Plan is attached" and Plan/Changes/Tests/PR/Review "Not started".

const DONE_ITEM = { ...ITEM, source_status: "Done", work_state: "done", source_fields: { blockers: ["needs a decision"] } };
const ended = ({ plans = [], units = [], pullRequestUrls = [], agentSessions = [], item = DONE_ITEM } = {}) =>
  buildCodingSessionSummary({ item, changePlans: plans, changeUnits: units, pullRequestUrls, agentSessions });

test("A completed session has an outcome, not a current action, also with recorded blockers", () => {
  const nothing = ended();
  assert.equal(nothing.state, "completed");
  assert.equal(nothing.nextAction, "Completed. No change was made in this session.");
  assert.doesNotMatch(nothing.nextAction, /Resolve blockers/);
  assert.equal(ended({ plans: [plan()] }).nextAction, "Completed · plan v1 · no code change");
  assert.equal(ended({ plans: [plan()], units: [UNIT], pullRequestUrls: ["https://git.example/pull/3"] }).nextAction,
    "Completed · plan v1 · 1 pull request");
  assert.equal(ended({ units: [UNIT] }).nextAction, "Completed · changes recorded, no pull request");
  const cancelled = ended({ item: { ...DONE_ITEM, source_status: "Cancelled", work_state: "cancelled" } });
  assert.equal(cancelled.nextAction, "Cancelled. No change was made in this session.");
});

test("An ended session lists only the steps that happened; none of them reads Not started", () => {
  const empty = ended();
  const none = stepsFor(empty, detailFor({ plans: [], units: [] }), null);
  assert.deepEqual(none.map((step) => [step.key, step.state, step.summary]),
    [["done", "done", "Completed. No change was made in this session."]]);

  const planned = ended({ plans: [plan({ status: "ready_for_review", approved_at: null })] });
  const steps = stepsFor(planned, detailFor({ plans: [plan({ status: "ready_for_review" })], units: [] }));
  assert.deepEqual(steps.map((step) => [step.key, step.state]), [["plan", "stopped"], ["done", "done"]],
    "a plan still waiting when the session ended is Not finished, not In progress");
  assert.ok(steps.every((step) => step.state !== "pending"));
});

test("rendered: the completed detail shows its outcome; no current action, no plan notice, no Start agent", () => {
  const view = render({ session: ended(), detail: detailFor({ plans: [], units: [] }) });
  const cockpit = view.root.find((node) => node.props?.className === "coding-cockpit");
  assert.match(text(cockpit), /^OutcomeCompleted\. No change was made in this session\.$/);
  assert.doesNotMatch(text(view.root), /Current action|No Change Plan|Not started|Work review/);
  assert.equal(view.root.findAll((node) => node.type === "button" && text(node) === "Start agent").length, 0);
  assert.doesNotMatch(text(view.root), /The session is complete\./);
  const labels = view.root.findAll((node) => typeof node.props?.["data-testid"] === "string"
    && node.props["data-testid"].startsWith("coding-step-") && node.type === "section").map((node) => node.props["aria-label"]);
  assert.deepEqual(labels.slice(0, 1), ["Done: Done"]);
  act(() => view.unmount());

  const running = render({ session: sessionFor({ state: "implementing", agentSessions: [AGENT] }), detail: detailFor() });
  assert.match(text(running.root.find((node) => node.props?.className === "coding-cockpit")), /^Current action/);
  act(() => running.unmount());
});
