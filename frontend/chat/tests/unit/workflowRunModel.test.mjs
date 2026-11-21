import assert from "node:assert/strict";
import test from "node:test";

import { actionReady, runActionRequest, startRunBody } from "../../src/chat/workflowRun/workflowRunRequests.ts";
import { runAdoptedTexts, runStopText, sampleRunBadge, followUpFailure, INSTALL_LAUNCHER_HREF, SAMPLE_RUN_LABEL, runGateText, runLoopTexts, runFragmentText, runPositionText, runSliceTexts, reviewerNoticeView } from "../../src/chat/workflowRun/workflowRunModel.ts";
import { runFlagText, runStatusLabel, pauseTitle, runStatusTone } from "../../src/chat/workflowRun/workflowRunStatus.ts";
import { INBOX_KIND_LABELS } from "../../src/chat/inbox/inboxModel.ts";

const run = {
  id: "run-1",
  status: "running",
  waiting_kind: null,
  pause_reason: null,
  outcome: null,
  current_node: { id: "impl", title: "Implement", kind: "phase" },
  phase_position: { index: 2, total: 4 },
  loops: [{ edge_id: "e1", title: "Implement ↔ test", used: 2, limit: 3 }, { edge_id: "e2", title: "Idle", used: 0, limit: 0 }],
  gate: { state: "not_verified", results: [{ type: "tool_called", outcome: "failed", blocking: true, description: "Tests ran", detail: "" }] },
  waiting: null,
};

test("the banner names the phase position, the bounded loops and the open checks", () => {
  assert.equal(runPositionText(run), "Phase 2 of 4 · Implement");
  assert.deepEqual(runLoopTexts(run), ["Implement ↔ test 2/3"]);
  assert.equal(runGateText(run), "Open checks: Tests ran");
  assert.equal(runGateText({ ...run, gate: { state: "passed", results: [] } }), "Checks passed");
});

test("a node compiled from a fragment names the fragment and its version", () => {
  const fragment = { key: "sf-publish-prove", version: 1, ref: "publish_prove" };
  const atFragment = { ...run, current_node: { id: "reserve_publication", title: "Reserve publication", kind: "platform_action", fragment } };
  assert.equal(runPositionText(atFragment), "Reserve publication · sf-publish-prove v1");
  const phase = { ...run, current_node: { ...run.current_node, fragment } };
  assert.equal(runPositionText(phase), "Phase 2 of 4 · Implement · sf-publish-prove v1");
  assert.equal(runFragmentText({ ...fragment, version: null }), "sf-publish-prove");
});

test("a run starts with an optional repository and branch", () => {
  assert.deepEqual(startRunBody("pr-fix", "w1"), { workflow_key: "pr-fix", work_item_id: "w1" });
  assert.deepEqual(startRunBody("pr-fix", "w1", " github:o/r ", "feature/x"), {
    workflow_key: "pr-fix", work_item_id: "w1", repository: "github:o/r", branch: "feature/x" });
});

test("the run shows the slices its phase delegated to sub-agents", () => {
  assert.deepEqual(runSliceTexts(run), []);
  const sliced = { ...run, slices: [{ key: "s1", title: "Totals", status: "merged", iteration: 2 }] };
  assert.deepEqual(runSliceTexts(sliced), ["Slice Totals · merged · iteration 2"]);
});

test("a runtime pause names its cause from the code, not a generic runtime failure", () => {
  const paused = { ...run, status: "paused", pause_reason: "runtime_failed" };
  assert.equal(runStatusLabel({ ...paused, pause: { code: "agent_loop", loop_kind: "repeat" } }),
    "Paused · The agent repeated the same step — stopped to save tokens");
  assert.equal(runStatusLabel({ ...paused, pause: { code: "agent_loop", loop_kind: "noop" } }),
    "Paused · The agent only printed messages instead of working — stopped to save tokens");
  assert.equal(pauseTitle("runtime_failed", { code: "interrupted_by_restart" }),
    "The server restarted during this phase — continue to pick it up again");
  assert.equal(pauseTitle("runtime_failed", { code: "server_turn_refused_no_model" }),
    "The platform could not start this phase's turn — continue to try again");
  assert.equal(pauseTitle("runtime_failed", { code: "device_turn_usage_limit" }),
    "The Claude account on the device reached its usage limit");
  assert.equal(pauseTitle("runtime_failed", { code: "device_turn_error" }), "The device ended the phase without finishing it");
  // Unknown code or none: the reason's label.
  assert.match(pauseTitle("runtime_failed", { code: "something_new" }), /^The agent turn failed in the runtime/);
  assert.match(runStatusLabel(paused), /^Paused · The agent turn failed in the runtime/);
});

test("status labels and tones make paused and waiting runs stand out", () => {
  assert.equal(runStatusLabel({ ...run, status: "paused", pause_reason: "loop_limit" }), "Paused · A loop reached its limit");
  assert.equal(runStatusLabel({ ...run, status: "paused", pause_reason: "evidence_unresolved" }),
    "Paused · The platform could not match the test evidence — fix it, then re-check");
  assert.equal(runStatusLabel({ ...run, status: "waiting", waiting_kind: "awaiting_confirmation" }), "Waiting for your confirmation");
  assert.equal(runStatusTone("paused"), "attention");
  assert.equal(runStatusTone("failed"), "danger");
  assert.equal(runFlagText({ status: "paused", pause_reason: "loop_limit", waiting_kind: null }), "Run paused");
  assert.equal(runFlagText({ status: "running", pause_reason: null, waiting_kind: null }), null);
});

test("an action posts its key, its typed input and the payload hash it decides on", () => {
  assert.deepEqual(runActionRequest(run, { key: "resume_in_new_session", label: "x" }), {
    path: "/api/v1/workflow-runs/run-1/sessions",
    body: {},
  });
  const input = { name: "k", kind: "number", min: 1, max: 5, default: 1, label: "More iterations" };
  assert.deepEqual(
    runActionRequest({ ...run, waiting: { kind: "awaiting_confirmation", payload_hash: "sha256:abc" } }, { key: "continue", label: "Continue", input }, 2),
    { path: "/api/v1/workflow-runs/run-1/actions", body: { action: "continue", k: 2, payload_hash: "sha256:abc" } },
  );
});

import { loopLimitBody, runsListPath } from "../../src/chat/workflowRun/workflowRunRequests.ts";
import { RUN_STATUS_FILTERS } from "../../src/chat/workflowRun/workflowRunStatus.ts";

test("the Work item's loop override is a whole number or the workflow's own n", () => {
  assert.deepEqual(loopLimitBody(""), {});
  assert.deepEqual(loopLimitBody(" 4 "), { loop_limit: 4 });
  assert.ok("error" in loopLimitBody("0"));
  assert.ok("error" in loopLimitBody("2.5"));
});

test("the workflow runs list opens on the runs that need a decision", () => {
  assert.equal(RUN_STATUS_FILTERS[0].value, "attention");
  assert.equal(runsListPath("attention"), "/api/v1/workflow-runs?status=attention");
  assert.equal(runsListPath(""), "/api/v1/workflow-runs");
});

import { documentationView } from "../../src/chat/workflowRun/workflowRunModel.ts";
import { payloadView } from "../../src/chat/workflowRun/workflowRunPayloadView.ts";

test("a confirmation shows the typed payload it is bound to and what blocks it", () => {
  const contract = payloadView({
    kind: "awaiting_confirmation",
    subject: "test_contract",
    payload_hash: "sha256:x",
    payload: {
      subject: "test_contract",
      acceptance_criteria: [{ id: "AC1", text: "Totals round half up", validation_commands: ["pytest tests/test_totals.py"] }],
      blockers: [],
    },
  });
  assert.equal(contract.heading, "These tests must pass");
  assert.deepEqual(contract.lines, ["AC1: Totals round half up — pytest tests/test_totals.py"]);
  const drafted = payloadView({
    kind: "awaiting_confirmation",
    subject: "test_contract",
    payload: {
      change_plan_id: "p1", version: 2, plan_hash: "sha256:abcdef0123456789",
      acceptance_criteria: [
        { id: "AC1", text: "Rounds", tests: ["tests/test_t.py::test_r"], validation_commands: ["pytest tests/test_t.py"] },
        { id: "AC2", text: "Reads well", manual_only: true, manual_reason: "A person reads it" },
      ],
      open_questions: ["Which currency?"],
      blockers: [],
    },
  });
  assert.deepEqual(drafted.lines, [
    "Change plan v2 · abcdef012345",
    "AC1: Rounds — tests tests/test_t.py::test_r — pytest tests/test_t.py",
    "AC2: Reads well — manual (A person reads it); confirming takes it over",
    "Open question: Which currency?",
  ]);
  const roled = payloadView({
    kind: "awaiting_confirmation",
    subject: "test_contract",
    payload: {
      acceptance_criteria: [{
        id: "AC1", text: "Slugs", tests: ["t::new_one", "t::kept"], validation_commands: ["pytest t"],
        test_roles: { "t::new_one": "new", "t::kept": "regression" },
      }],
      blockers: ["t::kept is marked new but already passes on the branch"],
    },
  });
  assert.deepEqual(roled.lines, ["AC1: Slugs — tests t::new_one (new), t::kept (regression) — pytest t"]);
  assert.deepEqual(roled.blockers, ["t::kept is marked new but already passes on the branch"]);
  const repro = payloadView({
    kind: "awaiting_confirmation",
    subject: "reproduction",
    payload: { tests: ["t::x"], symptom: "assert 2 == 3", failing_tests: [{ id: "t::x", message: "assert 2 == 3" }] },
  });
  assert.deepEqual(repro.lines, ["Reproduced by t::x", "Symptom: assert 2 == 3", "Failing in the last test run: t::x"]);
  const shown = payloadView({
    kind: "awaiting_confirmation",
    subject: "advance",
    payload: { shows: "incident_hypothesis", output: { version: 1, cause: "Pool exhausted", code_fix_needed: true, sources: ["kb/1"] } },
  });
  assert.deepEqual(shown.lines, ["cause: Pool exhausted", "code fix needed: yes", "sources: kb/1"]);
  const missing = payloadView({ kind: "awaiting_confirmation", subject: "test_contract", payload: { missing: "No plan." } });
  assert.equal(missing.missing, "No plan.");
  const draft = payloadView({ kind: "awaiting_confirmation", subject: "ticket_draft", payload: { text: "Summary" } });
  assert.deepEqual([draft.heading, draft.text], ["Ticket draft", "Summary"]);
  assert.equal(payloadView({ kind: "waiting_for_reply" }), null);
  assert.equal(draft.testAlert, null);
  const alert = payloadView({ kind: "awaiting_confirmation", subject: "advance", payload: { test_alert: true } });
  assert.match(alert.testAlert, /test alert/);
});

test("the requester who authored the pull request is told to review and merge it, with a safe link only", () => {
  assert.equal(reviewerNoticeView({ reviewer_notice: null }), null);
  const notice = { reason: "requester_is_author", text: "You are this pull request's author", url: "https://scm.test/pr/3" };
  assert.deepEqual(reviewerNoticeView({ reviewer_notice: notice }), { text: notice.text, url: notice.url,
    linkAccount: false });
  assert.equal(reviewerNoticeView({ reviewer_notice: { ...notice, reason: "requester_unresolved",
    link_account: "atlassian" } }).linkAccount, true);
  assert.equal(reviewerNoticeView({ reviewer_notice: { ...notice, url: "javascript:alert(1)" } }).url, null);
  assert.equal(INBOX_KIND_LABELS.workflow_run_review_own_pr, "! review PR");
});

test("abort and stop post the reason the person gives; a failed step offers retry and a new branch name", () => {
  const abort = { key: "abort", label: "Abort", input: { name: "reason", kind: "text", label: "Why?", default: "", required: true } };
  assert.equal(actionReady(abort, ""), false);
  assert.equal(actionReady(abort, "  "), false);
  assert.equal(actionReady(abort, "Wrong repository"), true);
  assert.deepEqual(runActionRequest(run, abort, " Wrong repository ").body, { action: "abort", reason: "Wrong repository" });
  const rename = { key: "new_branch", label: "New name", input: { name: "branch", kind: "text", label: "Branch", default: "feature/x-2" } };
  assert.deepEqual(runActionRequest(run, rename, "feature/x-3").body, { action: "new_branch", branch: "feature/x-3" });
  assert.equal(runStatusLabel({ status: "paused", pause_reason: "action_failed" }), "Paused · A step failed — retry, change or abort");
  assert.equal(runStatusLabel({ status: "paused", pause_reason: "environment_not_ready" }),
    "Paused · The tests cannot run here yet — fix the environment, then retry");
  assert.equal(runStatusLabel({ status: "paused", pause_reason: "workspace_dirty" }),
    "Paused · The working folder has uncommitted changes — commit or stash, then retry");
});

test("the run card and the Work item show why a run stopped and what it took over from earlier runs", () => {
  assert.equal(runStopText({ stop: { reason: "Restart with the new definition" } }), "Stopped: Restart with the new definition");
  assert.equal(runStopText({ stop_reason: "Out of scope" }), "Stopped: Out of scope");
  assert.equal(runStopText({ stop: null }), null);
  assert.deepEqual(runAdoptedTexts({ adopted: {
    branch: { branch: "feature/BRD-8-x", from_runs: ["a5fa85f9"], decided_by: null },
    pull_request: { id: "12", from_run: "a5fa85f9" },
  } }), ["Branch taken over from run a5fa85f9", "Pull request taken over from run a5fa85f9"]);
});

test("an adopted branch says whether it was fast-forwarded or is behind the default branch", () => {
  assert.deepEqual(runAdoptedTexts({ adopted: {
    branch: { from_runs: ["r1"], commits: [], fast_forwarded_from: "abc", base_branch: "main" },
  } }), ["Branch taken over from run r1 · fast-forwarded to the current main"]);
  assert.deepEqual(runAdoptedTexts({ adopted: {
    branch: { from_runs: ["r1"], commits: ["c1"], behind_base: 2, base_branch: "main" },
  } }), ["Branch taken over from run r1 · 2 commits behind main (not moved: it has its own commits)"]);
});

test("documentation: the card links the published page", () => {
  assert.deepEqual(
    documentationView({ documentation: { url: "https://docs.example.test/wiki/x", title: "PAY-1: Totals",
      version: 2, knowledge: { item_state: "ingested", version: "2", page_version: 2, in_knowledge: true } } }),
    { title: "PAY-1: Totals", url: "https://docs.example.test/wiki/x", version: 2, inKnowledge: true },
  );
  assert.equal(documentationView({ documentation: { url: "javascript:alert(1)" } }).url, null);
});

test("documentation: 'in Knowledge' only for the exact published version the backend proved (AFS-7)", () => {
  const view = (version, knowledge) =>
    documentationView({ documentation: { url: "https://docs.example.test/wiki/x", title: "T", version, knowledge } });
  const proof = { item_state: "ingested", version: "1", page_version: 1, in_knowledge: true };
  assert.equal(view(1, proof).inKnowledge, true);
  // Page v1 published, Knowledge holds v2 (or the reverse): never green.
  assert.equal(view(1, { ...proof, version: "2" }).inKnowledge, false);
  assert.equal(view(2, proof).inKnowledge, false);
  // A bare ledger state is no proof.
  assert.equal(view(1, { item_state: "ingested", version: "1" }).inKnowledge, false);
  assert.equal(view(1, { ...proof, in_knowledge: false }).inKnowledge, false);
  // Withheld, unavailable, unknown.
  assert.equal(view(1, { ...proof, item_state: "withheld", in_knowledge: false }).inKnowledge, false);
  assert.equal(view(1, null).inKnowledge, false);
  assert.equal(view(null, proof).inKnowledge, false);
});

test("the ticket delivery review card lists each finding and each open assumption on its own line", () => {
  const view = payloadView({
    kind: "awaiting_confirmation",
    subject: "decisions",
    payload: {
      subject: "decisions", text: "Done.", shows: "review_verdict",
      output: {
        verdict: "pass", summary: "Fine.", at: "2026-11-10T13:00:00",
        findings: [{ severity: "low", file: "src/a.py", line: 3, fix: "Name it total." }],
        assumptions: ["Not in the inventory gives bonus 5: intended?"],
      },
    },
  });
  assert.ok(view.lines.includes("Finding src/a.py:3 [low] Name it total."));
  assert.ok(view.lines.includes("Open question 1: Not in the inventory gives bonus 5: intended?"));
});

test("a device turn retried after a model service error is a quiet wait, not a pause", () => {
  const run = { status: "waiting", waiting_kind: "awaiting_device", pause_reason: null, outcome: null,
    waiting: { kind: "awaiting_device", title: "Waiting for the device", reason: "model_service_retry" } };
  assert.equal(runStatusLabel(run), "Retrying after a model service error");
  assert.equal(runStatusLabel({ ...run, waiting: { kind: "awaiting_device" } }), "Waiting for the device");
});

test("an imported sample run carries the Sample run badge, every other run none", () => {
  assert.deepEqual(sampleRunBadge({ sample: true })?.label, SAMPLE_RUN_LABEL);
  assert.equal(SAMPLE_RUN_LABEL, "Sample run");
  assert.ok(sampleRunBadge({ sample: true })?.title.includes("imported into this demo"));
  assert.equal(sampleRunBadge({ sample: false }), null);
  assert.equal(sampleRunBadge({}), null);
  assert.equal(sampleRunBadge(null), null);
});

test("a triage whose follow-up did not start says so, and points to the launcher when the server may not build", () => {
  const refused = { state: "failed", workflow_key: "bug-fix-reproduction", code: "server_build_not_allowed",
    message: "This workflow builds or tests the repository (tests_green), which is not allowed on the Octryx server." };
  const card = followUpFailure({ routing: refused });
  assert.ok(card?.text.startsWith('The triage is done, but "bug-fix-reproduction" did not start: This workflow builds'));
  assert.equal(card?.needsDevice, true);
  const row = followUpFailure({ follow_up_failed: { workflow_key: "x", code: "requester_inactive", message: "Gone." } });
  assert.equal(row?.needsDevice, false);
  assert.equal(followUpFailure({ routing: { state: "routed", workflow_key: "x", run_id: "r" } }), null);
  assert.equal(followUpFailure({}), null);
  assert.equal(INSTALL_LAUNCHER_HREF, "/chat?area=agents&agents_view=install");
});

test("a review bot run offers no chat: its review is on the pull request", async () => {
  const { opensChat } = await import("../../src/chat/workflowRun/workflowRunModel.ts");
  assert.equal(opensChat({ workflow_key: "pr-review-bot" }), false);
  assert.equal(opensChat({ workflow_key: "bug-fix-reproduction" }), true);
});
