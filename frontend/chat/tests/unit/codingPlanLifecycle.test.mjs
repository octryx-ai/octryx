// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingPlanLifecycle.test.mjs
//
// A Work Plan's status is not the Work Item's delivery lifecycle. Root live counterexample
// (OPS-2 after the answer flow): plan v4 ready_for_review with zero runs, changed files,
// validation results and PRs made the session review_ready / reviewing with "Prepare pull request or
// review package", while Start agent correctly stayed disabled. Plan statuses keep the session in
// planning with the exact plan step; source, state-event and recorded execution states still decide
// review, testing, implementation, blocked, cancelled and completed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCodingSessionSummary } from "../../src/chat/coding/codingSessionModel.ts";
import { sessionInQueue } from "../../src/chat/coding/codingQueuePresenter.ts";

function item(overrides = {}, sourceFields = {}) {
  return {
    id: "ops-2", source_key: "OPS-2", title: "Synthetic operations item", description: "", source_status: "Open",
    work_state: "planning", sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [],
    source_fields: sourceFields, source_url: null, automation_eligibility: null, ...overrides,
  };
}

function plan(status, overrides = {}) {
  return {
    id: `plan-${status}`, work_item_id: "ops-2", version: 4, status, title: "OPS-2 plan", understood_request: "Analyse",
    assumptions: [], open_questions: [], affected_repositories: [], change_units: [], proposed_branches: [], planned_files: [],
    validation_plan: [{ command: "Manual verification of Work Plan outcome required.", source: "manual_required" }],
    acceptance_criteria: [], security_risks: [], reviewer_recommendations: [], required_approvals: [{ type: "work_plan", required: true }],
    expected_prs: [], rollback_plan: "", trace_refs: [], evidence: { plan_type: "analysis" }, jira_sync_preview: {}, created_by: "u1",
    ...overrides,
  };
}

const summary = (plans, itemOverrides = {}, sourceFields = {}, extra = {}) =>
  buildCodingSessionSummary({ item: item(itemOverrides, sourceFields), changePlans: plans, ...extra });

test("root counterexample: an unapproved analysis plan v4 in review is planning, not delivery review", () => {
  const session = summary([plan("ready_for_review")]);
  assert.equal(session.state, "planned");
  assert.equal(session.phase, "planning");
  assert.equal(session.nextAction, "Review Work Plan v4");
  assert.doesNotMatch(session.nextAction, /pull request|review package|repository/i, "no PR and no fake repository demand");
  assert.equal(session.recordedEvidenceCount, 0);
  assert.equal(sessionInQueue(session, "review"), false, "the Coding review queue is for code and PRs");
  assert.equal(sessionInQueue(session, "blocked"), false);
});

test("plan status matrix: each unapproved plan status keeps planning with the exact plan step", () => {
  const cases = [
    ["draft", {}, "Review draft Work Plan v4"],
    ["needs_clarification", { open_questions: ["Which profiles?"] }, "Answer the open questions on Work Plan v4"],
    ["needs_clarification", {}, "Create a new Work Plan version for the clarification on v4"],
    ["rejected", {}, "Create a new Work Plan version (v4 was rejected)"],
    ["superseded", {}, "Create a new Work Plan version"],
    ["ready_for_review", {}, "Review Work Plan v4"],
  ];
  for (const [status, overrides, nextAction] of cases) {
    const session = summary([plan(status, overrides)]);
    assert.deepEqual([session.state, session.phase, session.nextAction], ["planned", "planning", nextAction], status);
    assert.equal(session.latestPlanStatus, status);
    assert.notEqual(session.tone, "danger", status);
  }
  const approved = summary([plan("approved")]);
  assert.deepEqual([approved.state, approved.phase], ["approved", "ready_to_implement"]);
  assert.equal(approved.nextAction, "Create governed branch/workspace", "approved keeps the existing delivery step");
});

test("explicit source, state-event and recorded execution states keep precedence over the plan", () => {
  const pending = [plan("ready_for_review")];
  const cases = [
    [{ source_status: "Cancelled" }, {}, {}, "cancelled", "completed"],
    [{ source_status: "Done" }, {}, {}, "completed", "completed"],
    [{ work_state: "rejected" }, {}, {}, "cancelled", "completed"],
    [{ work_state: "blocked" }, {}, {}, "blocked", "blocked"],
    [{ work_state: "needs_clarification" }, {}, {}, "blocked", "blocked"],
    [{}, { requires_replan: true }, {}, "needs_replan", "blocked"],
    [{ work_state: "testing" }, {}, {}, "testing", "validating"],
    [{ work_state: "implementing" }, {}, {}, "implementing", "implementing"],
    [{ work_state: "review" }, {}, {}, "review_ready", "reviewing"],
    [{}, {}, { stateEvents: [{ to_state: "in_review", dry_run: false, created_at: "2026-10-04T10:00:00" }] }, "review_ready", "reviewing"],
    // A recorded pull request (work_pull_requests) opens the PR state; a copy on the item no longer does.
    [{}, {}, { pullRequestUrls: ["https://bitbucket.example/pr/7"] }, "pr_open", "reviewing"],
  ];
  for (const [itemOverrides, sourceFields, extra, state, phase] of cases) {
    const session = summary(pending, itemOverrides, sourceFields, extra);
    assert.deepEqual([session.state, session.phase], [state, phase], JSON.stringify([itemOverrides, sourceFields, extra]));
  }
  const reviewing = summary(pending, { work_state: "review" });
  assert.equal(reviewing.nextAction, "Prepare pull request or review package", "a real delivery review keeps its step");
  const withPr = summary(pending, {}, {}, { pullRequestUrls: ["https://bitbucket.example/pr/7"] });
  assert.equal(withPr.nextAction, "Review PR and handle feedback");
  const copyOnly = summary(pending, {}, { pull_requests: [{ url: "https://bitbucket.example/pr/7" }] });
  assert.notEqual(copyOnly.state, "pr_open", "the item's copy is not a PR source");
});

test("recorded blockers beyond the plan's own questions still come first; failed evidence still blocks", () => {
  const blocked = summary([plan("ready_for_review")], {}, { blockers: ["Repository profile missing"] });
  assert.equal(blocked.state, "planned");
  assert.equal(blocked.nextAction, "Resolve blockers or ask for clarification");
  const questionsOnly = summary([plan("needs_clarification", { open_questions: ["a", "b"] })]);
  assert.equal(questionsOnly.blockerCount, 2, "the plan's questions are still counted and shown");
  assert.equal(questionsOnly.nextAction, "Answer the open questions on Work Plan v4");
  const failed = summary([plan("needs_clarification")], {}, { pipeline: { status: "failed" } });
  assert.equal(failed.state, "blocked", "failed recorded evidence still blocks");
});

test("no plan and a closed item keep their existing states", () => {
  const none = summary([]);
  assert.deepEqual([none.state, none.phase, none.nextAction], ["draft", "ready_to_plan", "Create a change plan and select repositories"]);
  const closedRejected = summary([plan("rejected")], { source_status: "Closed" });
  assert.equal(closedRejected.state, "completed", "a closed item is still completed");
});
