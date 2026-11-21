// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingReviewSummary.test.mjs
//
// The Coding list, detail, queues and Policy audit show the backend reviewer verdict (the
// coding audit's reviewer_approval gate) for the exact latest plan. Root live negative: a recorded
// changes_requested decision blocked coding-audit, yet the Cockpit kept "0 blockers / Blocked 0".
// Unknown is "unavailable", never zero; a new decision invalidates the old verdict at once, a failed
// re-read stays unavailable with Retry, and late or older replies never overwrite a newer verdict.
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
import * as reader from "../../src/chat/coding/codingReviewSummary.ts";
import { codingQueueEmptyState, codingSessionsNote, sessionInQueue } from "../../src/chat/coding/codingQueuePresenter.ts";
import * as loadingState from "../../src/layout/LoadingState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const flush = () => act(async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); });
const Null = () => null;

function item(id = "ops-2", overrides = {}, sourceFields = {}) {
  return { id, source_key: id.toUpperCase(), title: `Item ${id}`, description: "", source_status: "Open", work_state: "in_progress",
    sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [], source_fields: sourceFields,
    source_url: null, automation_eligibility: null, ...overrides };
}

function plan(workItemId = "ops-2", version = 4, status = "approved") {
  return { id: `plan-${workItemId}-v${version}`, work_item_id: workItemId, version, status, title: `Plan v${version}`,
    understood_request: "", assumptions: [], open_questions: [], affected_repositories: [{ repository_name: "ops-repo" }],
    change_units: [], proposed_branches: [], planned_files: [], validation_plan: [], acceptance_criteria: [], security_risks: [],
    reviewer_recommendations: [], required_approvals: [], expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {},
    jira_sync_preview: {}, created_by: "u1" };
}

function unit(workItemId = "ops-2") {
  return { id: `unit-${workItemId}`, work_item_id: workItemId, repository_name: "ops-repo", branch_name: `feature/${workItemId}`,
    scope: "", expected_paths: [], validation_commands: [], reviewer_policy: {}, dependency_order: 0, status: "planned",
    updated_at: "2026-10-04T10:00:00.123456" };
}

const REASONS = {
  pass: "Every required review of plan v4 is approved.",
  block: "A current review decision on plan v4 requests changes or rejects.",
  review_required: "No current approval of plan v4 for ops-repo.",
  missing: "No review decision is recorded for plan v4.",
};

function candidateSummary(status, latest = plan()) {
  return { basis: "reviewer_approval", status, blocking: status === "block", reason: REASONS[status],
    plan_id: latest.id, plan_version: latest.version };
}

// The reviewer_approval gate exactly as coding_audit._gate serializes it: `blocking` is the audit's
// PR-readiness flag (BLOCKING_GATE_STATUSES = {block, failed, missing}); the evidence is
// evaluate_reviewer_gate's (no plan keys when the item has no plan).
const HEAD_LIMIT = "Decisions are bound to the plan version and Change Unit, not to a pull-request head commit; this is not merge readiness.";
function realReviewerGate(status, latest = plan()) {
  const evidence = latest
    ? { limit: HEAD_LIMIT, overrides: 0, plan_id: latest.id, plan_version: latest.version,
      scopes: [{ scope: "change_unit", change_unit_id: `unit-${latest.work_item_id}`, repository_name: "ops-repo",
        required_reviewers: [], requirement_readable: true, missing_reviewers: [], ambiguous_reviewers: [],
        current_decisions: [], satisfied: status === "pass" }],
      requirement_gaps: [], activity_count: 0 }
    : { limit: HEAD_LIMIT, overrides: 0, activity_count: 0 };
  return { key: "reviewer_approval", label: "Reviewer Approval", status, blocking: status === "block" || status === "missing",
    reason: latest ? REASONS[status] : "No Change Plan, so no review requirement is known.", evidence };
}

function auditReport(status, latest = plan()) {
  return {
    work_item_id: latest.work_item_id, source_key: "OPS-2", timeline: [],
    quality_gates: [
      { key: "change_plan", label: "Change Plan", status: "pass", blocking: false, reason: "ok", evidence: {} },
      realReviewerGate(status, latest),
    ],
    quality_summary: { status: status === "block" ? "blocked" : "review_required", total: 2, blocking: status === "block" ? 1 : 0, counts: {} },
    pr_summary: { title: "OPS-2", status: "review_required", request: "", implementation: [], files: [], repositories: [], branches: [],
      tests: [], risks: [], reviewers: [], ready_to_open_pr: false },
    evidence: { review_event_count: 1, pipeline_stage_count: 0 },
  };
}

// ---- reader: strict and bound to the exact latest plan --------------------------------------------

test("the list summary is used only when complete and bound to the latest plan id and version", () => {
  const latest = plan();
  assert.deepEqual(reader.reviewSummaryFromCandidate(candidateSummary("block"), latest),
    { status: "block", reason: REASONS.block, planId: latest.id, planVersion: 4 });
  const invalid = { status: "unavailable", cause: "invalid" };
  for (const broken of [
    { ...candidateSummary("block"), plan_version: 3 },
    { ...candidateSummary("block"), plan_id: "plan-other" },
    { ...candidateSummary("pass"), blocking: true },
    { ...candidateSummary("block"), basis: undefined },
    { ...candidateSummary("block"), status: "approved" },
    { ...candidateSummary("block"), reason: 7 },
  ]) assert.deepEqual(reader.reviewSummaryFromCandidate(broken, latest), invalid, JSON.stringify(broken));
  for (const absent of [undefined, null, "block", []]) {
    assert.deepEqual(reader.reviewSummaryFromCandidate(absent, latest), { status: "unavailable", cause: "not_loaded" });
  }
  const noPlan = { basis: "reviewer_approval", status: "missing", blocking: false, reason: "No Change Plan", plan_id: null, plan_version: null };
  assert.equal(reader.reviewSummaryFromCandidate(noPlan, null).status, "missing");
  assert.deepEqual(reader.reviewSummaryFromCandidate({ ...noPlan, status: "block", blocking: true }, null), invalid);
});

test("real audit gates for pass, block, review_required and missing are known verdicts; missing blocks only the audit", () => {
  const latest = plan();
  for (const status of ["pass", "block", "review_required", "missing"]) {
    const report = { quality_gates: [realReviewerGate(status, latest)] };
    assert.deepEqual(reader.reviewSummaryFromAuditReport(report, latest),
      { status, reason: REASONS[status], planId: latest.id, planVersion: 4 }, status);
  }
  const noPlan = { quality_gates: [realReviewerGate("missing", null)] };
  assert.equal(reader.reviewSummaryFromAuditReport(noPlan, null).status, "missing");
  // The list flag is narrower: only a current negative review blocks there.
  assert.equal(reader.reviewSummaryFromCandidate({ ...candidateSummary("missing"), blocking: true }, latest).status, "unavailable");
  for (const [status, blocking] of [["missing", false], ["pass", true], ["review_required", true], ["block", false]]) {
    const report = { quality_gates: [{ ...realReviewerGate(status, latest), blocking }] };
    assert.equal(reader.reviewSummaryFromAuditReport(report, latest).status, "unavailable", `${status} with blocking=${blocking}`);
  }
  const missingSession = summary(reader.reviewSummaryFromAuditReport({ quality_gates: [realReviewerGate("missing", latest)] }, latest));
  assert.equal(missingSession.blockerCount, 0, "a missing review is not a blocker in Coding");
  assert.notEqual(missingSession.state, "changes_requested");
});

test("the Sessions note discloses unavailable work reviews (the Blocked count may miss one)", () => {
  const known = summary(reader.reviewSummaryFromCandidate(candidateSummary("missing"), plan()));
  const unknown = summary(reader.unavailableReview("refresh_failed"));
  assert.equal(codingSessionsNote([known]), null);
  assert.equal(codingSessionsNote([known, unknown, unknown]), "2 work reviews unavailable, so Blocked may miss a session");
});

test("an empty Blocked queue says 'no known' while reviews are unavailable; true and filtered empties are unchanged", () => {
  const base = { queueCount: 0, workItemCount: 3, search: "" };
  const trueEmpty = codingQueueEmptyState("blocked", base);
  assert.equal(trueEmpty.title, "No coding session is blocked.");
  assert.deepEqual(codingQueueEmptyState("blocked", { ...base, unavailableReviewCount: 0 }), trueEmpty);
  const unknown = codingQueueEmptyState("blocked", { ...base, unavailableReviewCount: 2 });
  assert.equal(unknown.title, "No known blocked coding session.");
  assert.match(unknown.body, /^2 coding sessions have no current work review verdict/);
  assert.match(unknown.body, /use Retry in its overview/);
  assert.deepEqual(unknown.actions, [{ kind: "openQueue", label: "Open all sessions", queue: "sessions" }]);
  assert.match(codingQueueEmptyState("blocked", { ...base, unavailableReviewCount: 1 }).body, /^1 coding session has/);
  const filtered = codingQueueEmptyState("blocked", { ...base, queueCount: 2, search: "pay", unavailableReviewCount: 2 });
  assert.equal(filtered.title, 'No coding session in this queue matches "pay".');
  for (const queue of ["sessions", "review", "completed"]) {
    assert.deepEqual(codingQueueEmptyState(queue, { ...base, unavailableReviewCount: 2 }), codingQueueEmptyState(queue, base), queue);
  }
});

test("an unknown verdict never reads as zero blockers", () => {
  const unknown = reader.unavailableReview("refresh_failed");
  assert.equal(reader.blockerCountText(0, unknown), "0 known blockers (work review unknown)");
  assert.equal(reader.blockerCountText(0, unknown, false), "0 known (work review unknown)");
  const known = reader.reviewSummaryFromCandidate(candidateSummary("missing"), plan());
  assert.equal(reader.blockerCountText(0, known), "0 blockers");
  assert.equal(reader.blockerCountText(1, known), "1 blocker");
  assert.equal(reader.blockerCountText(2, known), "2 blockers");
  assert.equal(reader.blockerCountText(1, unknown), "1 known blocker (work review unknown)");
});

test("the audit gate is read the same way; a duplicated or foreign-plan gate is unavailable", () => {
  const latest = plan();
  assert.equal(reader.reviewSummaryFromAuditReport(auditReport("block"), latest).status, "block");
  assert.deepEqual(reader.reviewSummaryFromAuditReport(null, latest), { status: "unavailable", cause: "not_loaded" });
  assert.equal(reader.reviewSummaryFromAuditReport(auditReport("block", plan("ops-2", 3)), latest).status, "unavailable");
  const doubled = auditReport("pass");
  doubled.quality_gates.push({ ...doubled.quality_gates[1], status: "block", blocking: true });
  assert.equal(reader.reviewSummaryFromAuditReport(doubled, latest).status, "unavailable");
});

// ---- model: the verdict's place in the lifecycle ---------------------------------------------------

function summary(review, overrides = {}, sourceFields = {}, plans = [plan()]) {
  return buildCodingSessionSummary({ item: item("ops-2", overrides, sourceFields), changePlans: plans, changeUnits: [unit()], review });
}

test("root negative: a blocking verdict is changes requested, one blocker, Blocked tile and an explicit next step", () => {
  const blocked = summary(reader.reviewSummaryFromCandidate(candidateSummary("block"), plan()));
  assert.deepEqual([blocked.state, blocked.phase, blocked.blockerCount], ["changes_requested", "blocked", 1]);
  assert.equal(blocked.nextAction, "Address the work review decision on plan v4");
  assert.equal(sessionInQueue(blocked, "blocked"), true);
  assert.equal(reader.reviewSummaryLabel(blocked.review), "Work review: changes requested or rejected");
});

test("terminal, replan, human-review and execution-blocked states keep precedence over a blocking review", () => {
  const block = reader.reviewSummaryFromCandidate(candidateSummary("block"), plan());
  assert.equal(summary(block, { source_status: "Cancelled" }).state, "cancelled");
  assert.equal(summary(block, { source_status: "Done" }).state, "completed");
  assert.equal(summary(block, {}, { requires_replan: true }).state, "needs_replan");
  assert.equal(summary(block, {}, { source_evidence_stale: true }).state, "needs_human_review");
  assert.equal(summary(block, { work_state: "blocked" }).state, "blocked");
});

test("pass, incomplete, missing and unavailable never add blockers; pass is not PR readiness; unavailable is not zero", () => {
  const base = summary(reader.unavailableReview("not_loaded"));
  for (const status of ["pass", "review_required", "missing"]) {
    const session = summary(reader.reviewSummaryFromCandidate(candidateSummary(status), plan()));
    assert.deepEqual([session.state, session.blockerCount, session.nextAction], [base.state, base.blockerCount, base.nextAction], status);
  }
  assert.equal(reader.reviewSummaryLabel(reader.reviewSummaryFromCandidate(candidateSummary("pass"), plan())),
    "Work review: approved (not PR readiness)");
  assert.equal(reader.reviewSummaryLabel(base.review), "Work review: unavailable");
  assert.equal(base.state, "approved", "an approved Work Plan stays a plan state, not a work review");
});

// ---- the real Coding workspace ---------------------------------------------------------------------

function deferred() {
  let resolve; let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    if (name.endsWith("/layout/LoadingState")) return loadingState;
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
    vm.runInNewContext(output, { module, exports: module.exports, window: globalThis.window, URL, URLSearchParams, Intl, console,
      require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

// One or two items; `audits` is the queue of coding-audit replies the workspace will receive.
function backend({ items = ["ops-2"], listStatus = "pass", detailAudit = (id) => auditReport("pass", plan(id)), sourceFields = {}, pullRequests = [] } = {}) {
  const state = { auditCalls: [], audits: [], posts: [] };
  const candidates = items.map((id) => ({
    work_item: item(id, {}, sourceFields), change_plans: [plan(id)], change_units: [unit(id)], state_events: [], agent_sessions: [],
    pull_requests: pullRequests, review_summary: candidateSummary(listStatus, plan(id)),
  }));
  const codingApi = {
    loadCodingWorkspaceData: async () => ({ items: candidates.map((entry) => entry.work_item), sessionCandidates: candidates, repositoryProfiles: [] }),
    loadCodingSessionDetail: async (id) => ({
      workItem: item(id, {}, sourceFields), changePlans: [plan(id)], changeUnits: [unit(id)], reviewerPayload: null, stateEvents: [],
      pipelineTrace: null, reviewEventsPayload: { items: [] }, auditReport: detailAudit(id), cicdPipelineTraces: null,
      cicdFindings: null, observability: null,
    }),
    startCodingAgentExecution: async () => ({}),
    loadCodingAuditReport: (id) => {
      state.auditCalls.push(id);
      const next = state.audits.shift();
      return next ? next.promise : Promise.reject(new Error("no audit reply scripted"));
    },
  };
  const workApi = {
    loadCodingReviewEvents: async () => ({ items: [], agent_feedback_context: null }),
    createCodingReviewEvent: async (workItemId, payload) => {
      state.posts.push(payload);
      return { id: `event-${state.posts.length}`, work_item_id: workItemId, event_type: payload.event_type, status: payload.decision,
        file_path: "", body: "", created_at: "2026-10-04T12:00:00", created_by: "user-alice",
        metadata: { review_decision_record: { decision: payload.decision, change_plan_id: payload.change_plan_id,
          change_unit_id: payload.change_unit_id, actor_label: "Alice Reviewer" } }, agent_context: {} };
    },
  };
  return { state, codingApi, workApi };
}

// Review ready, Blocked and Completed are filter tabs of Sessions (label + count).
const tab = (root, label) => root.findAll((node) => node.props?.role === "tab" && text(node).startsWith(label))[0];

// Opens the Details section of the shown session (its counters live there).
function openDetails(root) {
  const head = root.findAll((node) => node.type === "button" && node.props?.className === "coding-step__head" && /^Details/.test(text(node)))[0];
  if (head && head.props["aria-expanded"] !== true) act(() => head.props.onClick());
}

function renderWorkspace(fake, search = "?area=coding&work_item_id=ops-2") {
  globalThis.window = {
    location: { search, href: `https://octryx.example/chat${search}` },
    history: { replaceState: () => {} },
    localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true,
  };
  const loadModule = makeLoader({
    "./codingApi": fake.codingApi,
    "/work/workApi": fake.workApi, "/work/workChangePlanApi": fake.workApi, "/work/workCodingApi": { ...fake.workApi, ...fake.codingApi },
    "@monaco-editor/react": { Editor: Null, DiffEditor: Null },
    "/CodingDeliveryPipeline": { CodingDeliveryPipeline: Null },
    "/CodingEffectiveRules": { CodingEffectiveRules: Null },
    "/CodingRepositoriesPage": { CodingRepositoriesPage: Null },
    "/CodingCicdProviders": { CodingCicdProviders: Null },
    "/CodingSessionStartDialog": { CodingSessionStartDialog: Null },
    "/CodingPipelineTracePanel": { CodingPipelineTracePanel: Null },
    "/CodingRuntimeObservability": { RuntimeObservabilityDeepDive: Null, RuntimeObservabilitySummary: Null },
    "/CodingWorkspaceEvidence": { CodingWorkspaceEvidence: Null },
  });
  const Workspace = loadModule("CodingAreaWorkspace.tsx").CodingAreaWorkspace;
  let view;
  act(() => { view = TestRenderer.create(createElement(Workspace)); });
  return view;
}

const button = (root, label) => root.findAll((node) => node.type === "button" && text(node) === label);
// The session reads as steps; a step or closing section opens by its header (and stays open).
const openStep = (root, key) => {
  const section = root.find((node) => node.props?.["data-testid"] === `coding-step-${key}`);
  const head = section.find((node) => node.type === "button" && node.props["aria-expanded"] !== undefined);
  if (!head.props["aria-expanded"]) act(() => head.props.onClick());
};
const card = (root, id) => root.find((node) => node.type === "button" && (node.props.className || "").includes("coding-session-card")
  && text(node).includes(id.toUpperCase()));
// A card shows title, state and next step; its facts (verdict, blockers) are its tooltip.
const cardText = (root, id) => { const node = card(root, id); return `${text(node)} · ${node.props.title || ""}`; };
const tileValue = (root, label) => {
  const all = text(root);
  const match = new RegExp(`${label}(\\d+)`).exec(all);
  return match ? Number(match[1]) : null;
};

async function recordDecision(view, decision) {
  openStep(view.root, "review");
  await flush();
  const form = view.root.find((node) => node.props?.["aria-label"] === "Review decision");
  act(() => form.findAll((node) => node.type === "select")[1].props.onChange({ target: { value: decision } }));
  await act(async () => { await button(view.root, "Record decision")[0].props.onClick(); });
}

function cleanup(view) {
  act(() => view.unmount());
  delete globalThis.window;
}

test("rendered: a recorded negative decision invalidates the passing verdict at once, then shows the blocking one", async () => {
  const fake = backend();
  const view = renderWorkspace(fake);
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: approved \(not PR readiness\)/);
  const audit = deferred();
  fake.state.audits.push(audit);

  await recordDecision(view, "changes_requested");
  assert.equal(fake.state.posts.length, 1);
  assert.deepEqual(fake.state.auditCalls, ["ops-2"], "one audit read for this item, no per-row audits");
  assert.match(cardText(view.root, "ops-2"), /Work review: updating after the new decision/);
  assert.doesNotMatch(text(view.root), /approved \(not PR readiness\)/, "the old passing verdict is gone while refreshing");

  await act(async () => { audit.resolve(auditReport("block")); });
  await flush();
  const shown = cardText(view.root, "ops-2");
  assert.match(shown, /changes requested/);
  assert.match(shown, /1 blocker(?!s)/);
  assert.match(shown, /Work review: changes requested or rejected/);
  assert.equal(tileValue(view.root, "Blocked"), 1);
  openStep(view.root, "rules");
  await flush();
  assert.match(text(view.root), /PR quality gatesblocked/, "the Policy audit shows the re-read report");
  cleanup(view);
});

test("rendered: a failed re-read stays unavailable with Retry and never shows the earlier pass; Retry reads again", async () => {
  const fake = backend();
  const view = renderWorkspace(fake);
  await flush();
  const failed = deferred();
  fake.state.audits.push(failed);
  await recordDecision(view, "changes_requested");
  await act(async () => { failed.reject(new Error("coding-audit failed")); });
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: unavailable, the update after the new decision failed/);
  assert.match(cardText(view.root, "ops-2"), /0 known blockers \(work review unknown\)/);
  assert.doesNotMatch(cardText(view.root, "ops-2"), /(^|[^n] )0 blockers/);
  assert.doesNotMatch(text(view.root), /approved \(not PR readiness\)/);
  openStep(view.root, "rules");
  await flush();
  assert.match(text(view.root), /No audit report captured yet/, "the Policy audit does not keep the old report either");

  // The current-action card with its Retry stays above the steps.
  const retry = deferred();
  fake.state.audits.push(retry);
  act(() => button(view.root, "Retry")[0].props.onClick());
  await act(async () => { retry.resolve(auditReport("block")); });
  await flush();
  assert.deepEqual(fake.state.auditCalls, ["ops-2", "ops-2"]);
  assert.match(cardText(view.root, "ops-2"), /Work review: changes requested or rejected/);
  cleanup(view);
});

test("rendered: an older reply for the same item never overwrites a newer verdict", async () => {
  const fake = backend();
  const view = renderWorkspace(fake);
  await flush();
  const first = deferred();
  const second = deferred();
  fake.state.audits.push(first, second);
  await recordDecision(view, "approved");
  await recordDecision(view, "changes_requested");
  assert.deepEqual(fake.state.auditCalls, ["ops-2", "ops-2"]);
  await act(async () => { second.resolve(auditReport("block")); });
  await act(async () => { first.resolve(auditReport("pass")); });
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: changes requested or rejected/);
  cleanup(view);
});

test("rendered: a reply for the previous item updates only that item, never the newly selected detail", async () => {
  const fake = backend({ items: ["ops-2", "ops-3"] });
  const view = renderWorkspace(fake);
  await flush();
  const late = deferred();
  fake.state.audits.push(late);
  await recordDecision(view, "changes_requested");
  act(() => card(view.root, "ops-3").props.onClick());
  await flush();
  await act(async () => { late.resolve(auditReport("block", plan("ops-2"))); });
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: changes requested or rejected/);
  assert.match(cardText(view.root, "ops-3"), /Work review: approved \(not PR readiness\)/);
  openStep(view.root, "rules");
  await flush();
  assert.match(text(view.root), /PR quality gatesreview_required/, "ops-3 keeps its own audit report");
  cleanup(view);
});

test("rendered: a reply bound to an older plan version is unavailable, not a verdict", async () => {
  const fake = backend();
  const view = renderWorkspace(fake);
  await flush();
  const stale = deferred();
  fake.state.audits.push(stale);
  await recordDecision(view, "changes_requested");
  await act(async () => { stale.resolve(auditReport("block", plan("ops-2", 3))); });
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: unavailable/);
  assert.doesNotMatch(cardText(view.root, "ops-2"), /Work review: (changes requested|approved)/);
  cleanup(view);
});

test("rendered: a failed detail audit read is unavailable with Retry instead of the older list value", async () => {
  const fake = backend({ detailAudit: () => null });
  const view = renderWorkspace(fake);
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: unavailable/);
  assert.doesNotMatch(cardText(view.root, "ops-2"), /approved \(not PR readiness\)/);
  assert.equal(button(view.root, "Retry").length, 1);
  cleanup(view);
});

test("rendered: the selected item stays open when its new verdict moves it out of the Review Ready queue", async () => {
  const fake = backend({ pullRequests: [{ pr_url: "https://bitbucket.example/pr/7" }] });
  const view = renderWorkspace(fake);
  await flush();
  act(() => tab(view.root, "Review ready").props.onClick());
  await flush();
  assert.ok(view.root.findAll((node) => node.props?.["aria-label"] === "Coding Session detail").length === 1);
  const audit = deferred();
  fake.state.audits.push(audit);
  await recordDecision(view, "changes_requested");
  await act(async () => { audit.resolve(auditReport("block")); });
  await flush();
  assert.equal(view.root.findAll((node) => node.props?.["aria-label"] === "Coding Session detail").length, 1,
    "the detail is still shown although the queue no longer lists the item");
  assert.match(text(view.root.find((node) => node.props?.["aria-label"] === "Coding Session detail")), /changes requested/);
  cleanup(view);
});

test("rendered: an empty Blocked queue with an unavailable review leads to the cockpit and Retry", async () => {
  const fake = backend({ detailAudit: () => null });
  const view = renderWorkspace(fake);
  await flush();
  act(() => tab(view.root, "Blocked").props.onClick());
  await flush();
  let page = text(view.root);
  assert.match(page, /No known blocked coding session\./);
  assert.match(page, /1 coding session has no current work review verdict/);
  assert.doesNotMatch(page, /No coding session is blocked\./);
  assert.match(page, /1 work review unavailable, so Blocked may miss a session/, "the Sessions note and the empty state agree");

  act(() => button(view.root, "Open all sessions")[0].props.onClick());
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: unavailable/);
  const audit = deferred();
  fake.state.audits.push(audit);
  act(() => button(view.root, "Retry")[0].props.onClick());
  await act(async () => { audit.resolve(auditReport("block")); });
  await flush();
  assert.match(cardText(view.root, "ops-2"), /Work review: changes requested or rejected/);

  act(() => tab(view.root, "Blocked").props.onClick());
  await flush();
  page = text(view.root);
  assert.match(cardText(view.root, "ops-2"), /changes requested/, "the reviewed session is now in the Blocked queue");
  assert.doesNotMatch(page, /No known blocked coding session/);
  cleanup(view);
});

test("rendered: with every verdict known, an empty Blocked queue still says no session is blocked", async () => {
  const fake = backend();
  const view = renderWorkspace(fake);
  await flush();
  act(() => tab(view.root, "Blocked").props.onClick());
  await flush();
  const page = text(view.root);
  assert.match(page, /No coding session is blocked\./);
  assert.doesNotMatch(page, /No known blocked|work reviews? unavailable/);
  cleanup(view);
});

test("rendered Overview: the work review is one line in the current-action card; the counters sit under Details", async () => {
  const fake = backend({ detailAudit: () => null });
  const view = renderWorkspace(fake);
  await flush();
  const primary = view.root.find((node) => node.props?.className === "coding-cockpit__primary");
  const reviewLine = primary.find((node) => node.type === "p" && /^Work review: /.test(text(node)));
  assert.equal(reviewLine.props.role, "status");
  assert.match(text(reviewLine), /^Work review: unavailable Retry$/);
  assert.equal(reviewLine.findAll((node) => node.type === "button" && text(node) === "Retry").length, 1);
  assert.equal(primary.findAll((node) => node.type === "dt").length, 0, "no counters next to the current action");
  openDetails(view.root);
  const side = view.root.find((node) => node.props?.className === "coding-detail__counters");
  assert.deepEqual(side.findAll((node) => node.type === "dt").map(text).slice(0, 3), ["Phase", "Blockers", "Recorded evidence"]);
  assert.equal(text(side.findAll((node) => node.type === "dd")[1]), "0 known (work review unknown)");

  const audit = deferred();
  fake.state.audits.push(audit);
  act(() => reviewLine.findByType("button").props.onClick());
  assert.match(text(view.root.find((node) => node.props?.className === "coding-cockpit__primary")), /Work review: updating after the new decision…/);
  await act(async () => { audit.resolve(auditReport("block")); });
  await flush();
  const updated = view.root.find((node) => node.props?.className === "coding-cockpit__primary");
  assert.match(text(updated), /Work review: changes requested or rejected/);
  assert.equal(updated.findAll((node) => node.type === "button").length, 0, "no Retry for a known verdict");
  const sideNow = view.root.find((node) => node.props?.className === "coding-detail__counters");
  assert.equal(text(sideNow.findAll((node) => node.type === "dd")[1]), "1");
  cleanup(view);
});


test("rendered: an empty Workspace (ux-first-run) shows Get started, no metric chips and no error", async () => {
  const fake = backend({ items: [] });
  const view = renderWorkspace(fake, "?area=coding");
  await flush();
  const page = text(view.root);
  assert.match(page, /Get started/);
  assert.match(page, /No work items to code on yet\./);
  assert.equal(view.root.findAll((node) => (node.props?.className || "").includes?.("coding-session-card")).length, 0);
  assert.doesNotMatch(page, /recorded evidence|blockers|PRs|could not|failed|error/i);
  cleanup(view);
});
test("rendered: the session filter uses the shared segments, not the unstyled admin tab classes", async () => {
  const view = renderWorkspace(backend());
  await flush();
  const group = view.root.find((node) => node.props?.["data-testid"] === "coding-session-tabs" && node.type === "div");
  assert.match(group.props.className, /\bds-segments\b/);
  assert.equal(group.props.role, "tablist");
  const tabs = group.findAll((node) => node.type === "button");
  assert.deepEqual(tabs.map((tab) => tab.props.role), ["tab", "tab", "tab", "tab", "tab"]);
  assert.equal(view.root.findAll((node) => /admin-channels__tab/.test(node.props?.className || "")).length, 0);
  cleanup(view);
});
