// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingPlannedVsRecorded.test.mjs
//
// Coding planned versus recorded evidence. A plan's checks and required approvals are
// intent, not results: unknown stays unknown, a recorded zero stays zero, failed checks never read
// as passed validation, and plan object keys are never counted as evidence. Renders the real queue
// card, trace, stepper, Tests view and detail tabs.
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
import * as evidence from "../../src/chat/coding/codingEvidenceModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

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
    vm.runInNewContext(output, { module, exports: module.exports, URL, URLSearchParams, Intl, console, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

const Null = () => null;
const loadModule = makeLoader({
  "/CodingAuditPanel": { CodingAuditPanel: Null },
  "/CodingPipelineTracePanel": { CodingPipelineTracePanel: Null },
  "/CodingRuntimeObservability": { RuntimeObservabilityDeepDive: Null, RuntimeObservabilitySummary: Null },
  "/CodingReviewWorkspace": { CodingReviewWorkspace: Null },
  "/CodingWorkspaceEvidence": { CodingWorkspaceEvidence: Null },
  "/CodingGovernanceKit": { GovernanceMetrics: Null },
});

function item(sourceFields = {}) {
  return {
    id: "ops-2", source_key: "OPS-2", title: "Synthetic operations item", description: "", source_status: "Open",
    work_state: "planning", sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [],
    source_fields: sourceFields, source_url: null, automation_eligibility: null,
  };
}

// The live OPS-2 shape: plan v2 needs clarification, one planned manual check, one required approval.
function opsPlan(overrides = {}) {
  return {
    id: "plan-v2", work_item_id: "ops-2", version: 2, status: "needs_clarification", title: "Clarify operations change",
    understood_request: "Operations change", assumptions: ["a"], open_questions: [], affected_repositories: [{ repository_name: "ops-repo" }],
    change_units: [], proposed_branches: [{ branch_name: "feature/OPS-2" }], planned_files: [{ path: "a" }, { path: "b" }],
    validation_plan: [{ name: "Manual verification required" }], acceptance_criteria: [], security_risks: [], reviewer_recommendations: [],
    required_approvals: [{ type: "work_plan", required: true }], expected_prs: [{ repository_name: "ops-repo", id: "expected-1", status: "expected" }],
    rollback_plan: "", trace_refs: [], evidence: { plan_type: "operations", runtime: { model: "x" } }, jira_sync_preview: {}, created_by: "u1",
    ...overrides,
  };
}

function observability(summary = {}, byName = []) {
  return {
    schema: "coding_observability.v1", work_item_id: "ops-2", source_key: "OPS-2", generated_from: {},
    summary: { status: "recorded", agent_session_count: 1, llm_call_count: 2, turn_trace_count: 1, tool_call_count: 3, failed_tool_call_count: 0,
      coding_audit_event_count: 0, platform_audit_event_count: 0, mutation_event_count: 0, validation_event_count: 0, repeated_tool_call_count: 0,
      total_tokens: 10, total_cost: "0.01", next_observation: "", ...summary },
    agent_sessions: [], usage: { total: {}, by_model: [], by_session: [] },
    tools: { total: 3, success: 3, failed: 0, by_kind: {}, by_name: byName, repeated_calls: [] }, turns: {}, audit: {}, timeline: [],
  };
}

const summaryFor = (sourceFields, plan = opsPlan()) => buildCodingSessionSummary({ item: item(sourceFields), changePlans: plan ? [plan] : [] });

// ---- model -----------------------------------------------------------------------------------

const UNKNOWN_TOOLS = { recorded: null, failed: null };
const stagesOf = (session, validation, preparedWorkspaces = 0) =>
  Object.fromEntries(evidence.codingProcessStages(session, { validation, preparedWorkspaces }).map((stage) => [stage.label, stage.complete]));

test("plan only, no run: planning is intent, not evidence, and nothing is recorded", () => {
  const session = summaryFor({});
  assert.equal(session.recordedEvidenceCount, 0, "plan keys, planned files, branches and repositories are not evidence");
  assert.deepEqual(session.validation, {
    planned: 1, results: { recorded: null, passed: null, failed: null, unrecognized: null }, toolCalls: UNKNOWN_TOOLS,
  });
  assert.deepEqual(session.approvals, { required: 1, recorded: null, granted: null, rejected: null, unrecognized: null, requirementsMet: false });
  assert.equal(evidence.validationLabel(session.validation), "No validation results recorded · 1 check planned");
  assert.equal(evidence.validationStatusWord(session.validation), "planned only");
  assert.equal(evidence.approvalLabel(session.approvals), "1 required · no approval records");
  assert.equal(session.isCodingRelevant, true, "planning still makes the item a Coding session");
  // The plan's own status (needs_clarification) keeps the session in planning, never blocked.
  assert.equal(session.state, "planned");
  assert.equal(session.phase, "planning");
  assert.equal(session.latestPlanStatus, "needs_clarification", "the actual plan status is kept");
});

test("expected PRs, proposed branches and planned files never become a linked PR, branch, change or review", () => {
  const plan = opsPlan({
    expected_prs: [{ repository_name: "ops-repo", url: "https://bitbucket.example/projects/OPS/repos/ops/pull-requests/7", status: "expected" }],
  });
  const session = summaryFor({}, plan);
  assert.deepEqual(session.pullRequests, [], "a proposed PR URL in the plan is not a live PR");
  assert.equal(session.recordedEvidenceCount, 0);
  assert.ok(session.branches.length > 0, "the planned branch stays visible as intent");
  const stages = stagesOf(session, session.validation);
  assert.equal(stages.Branch, false, "a planned branch is not a prepared branch");
  assert.equal(stages.Change, false);
  assert.equal(stages.Review, false);
});

test("a recorded zero stays zero and is never replaced by planned checks", () => {
  const fromSource = summaryFor({ validation_results: [] }).validation;
  assert.deepEqual(fromSource.results, { recorded: 0, passed: 0, failed: 0, unrecognized: 0 });
  assert.equal(evidence.validationLabel(fromSource), "0 validation results recorded · 1 check planned");
  assert.equal(evidence.validationStatusWord(fromSource), "none recorded");
  const fromRuntime = evidence.codingValidationEvidence({}, opsPlan(), observability({ validation_event_count: 0 }));
  assert.deepEqual(fromRuntime.toolCalls, { recorded: 0, failed: 0 });
  assert.equal(evidence.validationStatusWord(fromRuntime), "planned only", "tool calls never stand in for results");
});

test("a successful run_cli_command is a tool call, not a passed test", () => {
  // The backend counts any run_cli_command as "validation" by name and marks it success when its result
  // has no error key, so a successful `pwd` would look like a passed check if read as a result.
  const toolOnly = evidence.codingValidationEvidence({}, opsPlan(),
    observability({ validation_event_count: 1 }, [{ tool_name: "run_cli_command", kind: "validation", count: 1, success: 1, failed: 0 }]));
  assert.deepEqual(toolOnly.results, { recorded: null, passed: null, failed: null, unrecognized: null });
  assert.equal(evidence.validationAllPassed(toolOnly), false);
  assert.equal(evidence.validationLabel(toolOnly), "No validation results recorded · 1 check planned");
  assert.equal(evidence.validationToolCallLabel(toolOnly), "1 recorded tool call related to validation");
  assert.equal(stagesOf(summaryFor({}), toolOnly).Validate, false);
});

test("positive recorded validation needs explicit passed source results", () => {
  const recorded = evidence.codingValidationEvidence({ validation_results: [{ command: "npm run lint", status: "passed" }] }, opsPlan());
  assert.deepEqual(recorded.results, { recorded: 1, passed: 1, failed: 0, unrecognized: 0 });
  assert.equal(evidence.validationLabel(recorded), "1 recorded result, all passed · 1 check planned");
  assert.equal(evidence.validationAllPassed(recorded), true);
});

test("failed or outcome-less recorded checks never read as passed validation", () => {
  const failed = summaryFor({ validation_results: [{ command: "npm run build", status: "failed" }, { command: "lint", status: "passed" }] }).validation;
  assert.equal(evidence.validationOutcome(failed), "failed");
  assert.equal(evidence.validationLabel(failed), "1 failed of 2 recorded results · 1 check planned");
  assert.equal(evidence.validationTone(failed), "danger");
  const pending = summaryFor({ validation_results: [{ command: "a", status: "pending" }, { command: "b", status: "passed" }] }).validation;
  assert.equal(evidence.validationLabel(pending), "2 recorded results (1 passed, 0 failed, 1 without an outcome) · 1 check planned");
  assert.equal(evidence.validationAllPassed(pending), false);
});

test("missing, empty or malformed records are never counted by their keys", () => {
  const malformed = summaryFor({
    validation_results: { command: "npm test", status: "passed" },
    approvals: "alice",
    pipeline_runs: { a: 1, b: 2, c: 3 },
    ci_runs: [{}, null, "x", { id: "ci-1", status: "passed" }],
    execution_runs: "run",
    audit_timeline: [],
  });
  assert.deepEqual(malformed.validation.results, { recorded: null, passed: null, failed: null, unrecognized: null }, "an object is not a list of results");
  assert.equal(malformed.approvals.recorded, null, "a bare string is not an approval record");
  assert.equal(malformed.recordedEvidenceCount, 1, "only the one well-formed CI record counts");
  assert.deepEqual(evidence.recordList([{}, { status: "" }, { status: "failed" }]).length, 1);
  const emptyEntries = summaryFor({ validation_results: [{}, {}] }).validation;
  assert.deepEqual(emptyEntries.results, { recorded: 0, passed: 0, failed: 0, unrecognized: 2 }, "empty objects are not results");
  assert.equal(evidence.validationOutcome(emptyEntries), "inconclusive", "unreadable entries are not a recorded zero either");
});

test("approval records are read by their decision: rejected or pending is not granted", () => {
  assert.equal(evidence.approvalLabel(summaryFor({ approvals: [] }).approvals), "1 required · 0 granted, 0 rejected, 0 without a decision");
  const mixed = summaryFor({ approvals: [
    { username: "alice", status: "approved" }, { username: "bob", decision: "rejected" }, { username: "carol", state: "pending" }, { username: "dan" },
  ] });
  assert.deepEqual(mixed.approvals, { required: 1, recorded: 4, granted: 1, rejected: 1, unrecognized: 0, requirementsMet: false });
  assert.equal(evidence.approvalLabel(mixed.approvals), "1 required · 1 granted, 1 rejected, 2 without a decision");
  const undecided = summaryFor({ approvals: [{ username: "alice" }] });
  assert.equal(stagesOf(undecided, undecided.validation).Review, false, "an approval record without a decision grants nothing");
  const untyped = summaryFor({ approvals: [{ username: "alice", status: "approved" }] });
  assert.equal(stagesOf(untyped, untyped.validation).Review, false, "a granted record that names no requirement verifies nothing");
  assert.equal(untyped.recordedEvidenceCount, 1, "an approval record is recorded evidence");
});

// Two required approvals, as in the plan contract (`required_approvals[].type`).
const twoRequired = opsPlan({ required_approvals: [{ type: "work_plan", required: true }, { type: "code_review", required: true }] });
const reviewFor = (approvals, plan = twoRequired) => {
  const session = summaryFor({ approvals }, plan);
  return { session, review: evidence.codingProcessStages(session, { validation: session.validation, preparedWorkspaces: 0 }).find((stage) => stage.label === "Review") };
};

test("Review is checked only when every required approval type has its own granted record", () => {
  const approvedAndRejected = reviewFor([{ type: "work_plan", status: "approved" }, { type: "code_review", status: "rejected" }]);
  assert.equal(approvedAndRejected.review.complete, false, "the reproduced case: one approved and one rejected of two required");
  assert.equal(approvedAndRejected.review.note, "approval records present, not verified");
  assert.equal(evidence.approvalLabel(approvedAndRejected.session.approvals), "2 required · 1 granted, 1 rejected, 0 without a decision");

  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }]).review.complete, false, "partial: fewer granted than required");
  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }, { type: "work_plan", status: "approved" }]).review.complete, false,
    "duplicate approvals of one type do not satisfy a different requirement");
  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }, { type: "code_review", status: "pending" }]).review.complete, false);
  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }, { type: "code_review", status: "approved" }, {}]).review.complete, false,
    "an unreadable approval record keeps the review unverified");
  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }], opsPlan({ required_approvals: [{ required: true }] })).review.complete, false,
    "a requirement without a type cannot be matched");
  assert.equal(reviewFor([{ type: "work_plan", status: "approved" }], opsPlan({ required_approvals: [] })).review.complete, false,
    "nothing required: approval activity is not a verified review");

  const twoCodeReviews = opsPlan({ required_approvals: [{ type: "code_review", required: true }, { type: "code_review", required: true }] });
  assert.equal(reviewFor([{ type: "code_review", status: "approved" }], twoCodeReviews).review.complete, false,
    "one granted record never satisfies two requirements");
  assert.equal(reviewFor([{ type: "code_review", status: "approved" }, { type: "code_review", status: "approved" }], twoCodeReviews).review.complete, true);

  const eligible = reviewFor([{ type: "code_review", status: "approved" }, { type: "work_plan", decision: "granted" }]);
  assert.equal(eligible.review.complete, true, "each required type has its own granted record");
  assert.equal(eligible.session.approvals.requirementsMet, true);
});

test("an unreadable validation entry never improves the outcome (reproduced case)", () => {
  const session = summaryFor({ validation_results: [{ command: "npm test", status: "passed" }, {}] });
  assert.deepEqual(session.validation.results, { recorded: 1, passed: 1, failed: 0, unrecognized: 1 });
  assert.equal(evidence.validationOutcome(session.validation), "inconclusive");
  assert.equal(evidence.validationLabel(session.validation),
    "1 recorded result (1 passed, 0 failed, 0 without an outcome) · 1 unreadable entry · 1 check planned");
  assert.doesNotMatch(evidence.validationLabel(session.validation), /all passed/);
  assert.equal(stagesOf(session, session.validation).Validate, false);
  assert.equal(evidence.approvalLabel(summaryFor({ approvals: [{ type: "work_plan", status: "approved" }, "x"] }).approvals),
    "1 required · 1 granted, 0 rejected, 0 without a decision, 1 unreadable");
});

test("a completed or cancelled source state never checks Change, Validate or Review", () => {
  const plan = opsPlan({ status: "approved" });
  const done = buildCodingSessionSummary({ item: { ...item({}), source_status: "Done" }, changePlans: [plan] });
  assert.equal(done.state, "completed", "the source state stays visible");
  assert.equal(done.phase, "completed");
  const doneStages = stagesOf(done, done.validation);
  assert.deepEqual([doneStages.Branch, doneStages.Change, doneStages.Validate, doneStages.Review], [false, false, false, false]);
  assert.equal(doneStages.Done, true, "Done reflects the source state only");

  const doneFailed = buildCodingSessionSummary({ item: { ...item({ validation_results: [{ command: "test", status: "failed" }] }), source_status: "Done" }, changePlans: [plan] });
  assert.equal(stagesOf(doneFailed, doneFailed.validation).Validate, false, "failed checks stay failed after Jira Done");

  const cancelled = buildCodingSessionSummary({ item: { ...item({}), source_status: "Cancelled" }, changePlans: [plan] });
  assert.equal(cancelled.state, "cancelled");
  const cancelledStages = stagesOf(cancelled, cancelled.validation);
  assert.deepEqual([cancelledStages.Validate, cancelledStages.Done], [false, false], "cancelled is not done");
});

test("the step indicator checks Branch only for a prepared workspace and Validate only for passed results", () => {
  const passed = summaryFor({ validation_results: [{ command: "test", status: "passed" }] });
  const stages = stagesOf(passed, passed.validation, 1);
  assert.equal(stages.Branch, true);
  assert.equal(stages.Validate, true);
  assert.equal(stages.Plan, true, "a plan record exists");
});

// ---- rendered consumers ----------------------------------------------------------------------

test("the queue card shows title, state and next step only; its counters are in the session's Details", () => {
  const { CodingSessionList } = loadModule("CodingSessionQueue.tsx");
  const session = summaryFor({});
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingSessionList, { sessions: [session], selectedId: null, onSelect: () => {} })); });
  const card = text(view.root);
  assert.match(card, new RegExp(session.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(card, new RegExp(session.statusLabel));
  assert.doesNotMatch(card, /recorded evidence|PRs|repo pending|check planned|Work review|blockers?/i, "no metric chips on the card");
  act(() => view.unmount());
});

function traceStep(root, label) {
  return root.findAll((node) => node.type === "li" && node.findAll((child) => child.type === "strong" && text(child) === label).length > 0)[0];
}

test("the execution trace never labels planned checks as captured and keeps unknown runtime unknown", () => {
  const { CodingExecutionTrace } = loadModule("CodingExecutionTrace.tsx");
  const session = summaryFor({});
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingExecutionTrace, { session, detail: null, latestPlan: opsPlan() })); });
  const validation = traceStep(view.root, "Validation");
  assert.match(text(validation), /planned only/);
  assert.match(text(validation), /No validation results recorded · 1 check planned/);
  assert.match(text(validation), /Planned: Manual verification required/);
  assert.doesNotMatch(text(validation), /captured/i);
  assert.match(text(traceStep(view.root, "Delivery")), /Approvals 1 required · no approval records/);
  assert.doesNotMatch(text(traceStep(view.root, "Agent run")), /0 tool calls/, "no runtime record is not zero calls");
  assert.match(text(traceStep(view.root, "Work plan")), /1 planned checks/);

  assert.match(text(traceStep(view.root, "Workspace & branch")), /not prepared/);
  assert.match(text(traceStep(view.root, "Workspace & branch")), /Planned: feature\/OPS-2/);

  // A successful generic CLI call recorded at runtime does not turn into passed validation.
  const detail = {
    observability: observability({ validation_event_count: 1 }, [{ tool_name: "run_cli_command", kind: "validation", count: 1, success: 1, failed: 0 }]),
    changeUnits: [], pipelineTrace: null, reviewerPayload: null,
  };
  act(() => view.update(createElement(CodingExecutionTrace, { session, detail, latestPlan: opsPlan() })));
  const runtime = text(traceStep(view.root, "Validation"));
  assert.match(runtime, /planned only/);
  assert.match(runtime, /1 recorded tool call related to validation/);
  assert.doesNotMatch(runtime, /passed/);
  act(() => view.unmount());
});

test("the Tests view separates recorded results from planned checks, with statuses", () => {
  const { CodingTestsEvidence } = loadModule("CodingTestsEvidence.tsx");
  const sourceFields = { validation_results: [{ command: "npm run build", status: "failed" }] };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(CodingTestsEvidence, {
      sourceFields, latestPlan: opsPlan(), observability: null, validation: evidence.codingValidationEvidence(sourceFields, opsPlan()),
    }));
  });
  const recorded = view.root.findByProps({ "aria-label": "Recorded validation" });
  const planned = view.root.findByProps({ "aria-label": "Planned checks" });
  assert.match(text(recorded), /npm run build/);
  assert.match(text(recorded), /failed/);
  assert.match(text(recorded), /1 failed of 1 recorded result/);
  assert.doesNotMatch(text(recorded), /Manual verification required/, "a planned check is not a recorded result");
  assert.match(text(planned), /Manual verification required/);
  assert.match(text(planned), /not results until a run records them/);
  assert.match(text(recorded), /No agent runtime record is linked/);
  act(() => view.unmount());
});

test("the detail Overview and Plan tabs report planned and recorded facts separately (OPS-2)", () => {
  const { CodingSessionDetail } = loadModule("CodingSessionDetail.tsx");
  const session = summaryFor({});
  const detail = {
    workItem: session.workItem, changePlans: [opsPlan()], changeUnits: [], reviewerPayload: null, stateEvents: [], pipelineTrace: null,
    reviewEventsPayload: null, auditReport: null, cicdPipelineTraces: null, cicdFindings: null, observability: null,
  };
  const render = (activeTab) => createElement(CodingSessionDetail, {
    session, detail, loading: false, activeTab, startingAgent: false, onTabChange: () => {}, onStartAgent: () => {}, onRestartAgent: () => {},
  });
  let view;
  act(() => { view = TestRenderer.create(render("process")); });
  const overview = text(view.root);
  assert.match(overview, /Recorded evidence0/, "the counters are under Details");
  assert.match(overview, /ValidationNo validation results recorded · 1 check planned/, "recorded and planned stay apart");
  assert.doesNotMatch(overview, /\bEvidence\d/);
  act(() => view.update(render("plan")));
  const plan = text(view.root);
  assert.match(plan, /Planned checks1/);
  assert.match(plan, /Recorded validationNo validation results recorded · 1 check planned/);
  assert.match(plan, /Approvals1 required · no approval records/);
  assert.doesNotMatch(plan, /Approvals are captured/);
  act(() => view.unmount());
});
