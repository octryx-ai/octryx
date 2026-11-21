// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/approvalOfferedDecisions.test.mjs
// Approvals after backend: the card offers exactly what the server lists (`offered_decisions`), a write to another
// system never gets "Always", and the approval detail page (GET /api/v1/approvals/{id}) reads as one view state.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  approvalCardModel,
  approvalDecisionErrorText,
  offeredDecisions,
} from "../../src/chat/approvalCardActions.ts";
import {
  approvalDecisionRequest,
  approvalDetailActions,
  approvalDetailHref,
  approvalDetailLinks,
  approvalDetailNote,
  approvalDetailState,
  approvalIdFromSearch,
  approvalPreviewKind,
  approvalTexts,
} from "../../src/chat/approval/approvalDetailModel.ts";
import { runHistory } from "../../src/chat/workflowRun/runHistoryModel.ts";

const kinds = (model) => model.actions.map((action) => action.kind);
const tool = (preview, standingRule = null) => ({
  status: "pending", standingRule, changePreview: preview === undefined ? null : { id: "p", preview },
});
const RULE = { toolName: "run_cli_command", argumentClass: "git status" };

test("the card shows Always only when the server offers it", () => {
  const admin = { canRetry: false, canGrantStandingConfirmation: true };
  // A REST or connector write: the server offers once and deny, even if a stale scope came along.
  assert.deepEqual(kinds(approvalCardModel(tool({ offered_decisions: ["once", "deny"] }, RULE), admin)), ["reject", "approve"]);
  // A local command whose standing rule is allowed.
  assert.deepEqual(kinds(approvalCardModel(tool({ offered_decisions: ["once", "always", "deny"] }, RULE), admin)),
    ["reject", "always", "approve"]);
  // Offered, but the viewer is no Workspace admin: the server would refuse it, so it is not shown.
  assert.deepEqual(kinds(approvalCardModel(tool({ offered_decisions: ["once", "always", "deny"] }, RULE),
    { canRetry: false, canGrantStandingConfirmation: false })), ["reject", "approve"]);
  // A preview without the list offers no Always, whatever scope came along.
  assert.deepEqual(kinds(approvalCardModel(tool({}, RULE), admin)), ["reject", "approve"]);
  assert.deepEqual(kinds(approvalCardModel(tool(undefined, null), admin)), ["reject", "approve"]);
  assert.equal(offeredDecisions({ offered_decisions: [] }), null, "an empty list says nothing");
  assert.deepEqual(offeredDecisions({ offered_decisions: ["once", "bogus", "deny"] }), ["once", "deny"]);
});

test("a refused decision reads as words; a 409 on Always says it cannot be a Workspace rule", () => {
  assert.match(approvalDecisionErrorText("always", 409), /cannot be allowed for the whole Workspace/);
  assert.match(approvalDecisionErrorText("approve", 409), /time ran out/);
  // An already decided approval is a 409 with its code on every path, also on "always".
  for (const decision of ["approve", "reject", "always"]) {
    assert.equal(
      approvalDecisionErrorText(decision, 409, "This approval was already decided.", "approval_already_resolved"),
      "This approval was already decided.",
    );
  }
  assert.match(approvalDecisionErrorText("reject", 403), /may not decide/);
});

const DETAIL = {
  id: "a1", kind: "session", status: "pending", action: "rest__desk__create_ticket", session_id: "s1", task_run_id: null,
  requested_by: "u1", approved_by: null, created_at: "2026-11-15T09:00:00Z", resolved_at: null,
  payload: { kind: "rest_request", toolName: "rest__desk__create_ticket", method: "POST", url: "http://127.0.0.1:8878/tickets",
    body: { title: "Printer", token: "[redacted]" } },
  offered_decisions: ["once", "deny"], decision_note: null, requested_by_name: "Anna", approved_by_name: null,
  workspace_id: "w1", workflow_run_id: null,
};

test("the detail page's view state: one sentence for every refusal, the detail when it loads", () => {
  assert.deepEqual(approvalDetailState(null), { kind: "loading" });
  assert.match(approvalDetailState({ status: 404 }).text, /does not exist or is not visible/);
  assert.match(approvalDetailState({ status: 403 }).text, /may not see/);
  assert.match(approvalDetailState({ status: 500 }).text, /HTTP 500/);
  assert.equal(approvalDetailState({ status: 200, payload: { id: "x" } }).kind, "message", "no status: unreadable");
  const ready = approvalDetailState({ status: 200, payload: DETAIL });
  assert.equal(ready.kind, "ready");
  assert.deepEqual([ready.detail.requestedByName, ready.detail.offered, ready.detail.workspaceId], ["Anna", ["once", "deny"], "w1"]);
  assert.equal(approvalPreviewKind(ready.detail.payload), "rest");
  assert.equal(approvalPreviewKind(null), "none");
  assert.equal(approvalIdFromSearch("?area=operations&tab=approvalDetail&approval=a1"), "a1");
  assert.equal(approvalIdFromSearch("?approval=../x"), null);
  assert.equal(approvalDetailHref("a 1"), "/chat?area=operations&tab=approvalDetail&approval=a%201");
});

test("the detail page offers the server's decisions while pending, nothing once decided or for a publication", () => {
  const detail = approvalDetailState({ status: 200, payload: DETAIL }).detail;
  assert.deepEqual(approvalDetailActions(detail).map((action) => action.label), ["Deny", "Allow once"]);
  assert.deepEqual(approvalDetailActions({ ...detail, offered: ["once", "always", "deny"] }).map((action) => action.kind),
    ["reject", "always", "approve"]);
  assert.deepEqual(approvalDetailActions({ ...detail, offered: ["once", "always", "deny"], kind: "task_run" }).map((a) => a.kind),
    ["reject", "approve"], "Always exists only for a chat's approval");
  assert.deepEqual(approvalDetailActions({ ...detail, offered: [] }), [], "nothing offered: no buttons");
  assert.deepEqual(approvalDetailActions(detail, "plan").map((action) => action.label), ["Reject", "Approve"]);
  assert.match(approvalDetailNote(approvalDetailActions(detail, "plan"), "plan"), /run without asking again/, "a plan covers its writes");
  assert.match(approvalDetailNote(approvalDetailActions(detail), "rest"), /Only this request/);
  assert.deepEqual(approvalDetailActions({ ...detail, status: "approved" }), []);
  assert.deepEqual(approvalDetailActions({ ...detail, kind: "governance" }), []);
  assert.deepEqual(approvalDecisionRequest(detail, "always"), { url: "/chat/api/approvals/a1/always" });
  assert.deepEqual(approvalDecisionRequest({ ...detail, kind: "task_run" }, "approve"), { url: "/api/v1/approvals/a1/approve", body: "{}" });
  assert.deepEqual(approvalDetailLinks(detail), [{ label: "Chat", text: "Open the chat ›", href: "/chat?session_id=s1" }]);
  assert.equal(approvalDetailLinks({ ...detail, workflowRunId: "r1" })[0].label, "Workflow run");
  assert.deepEqual(approvalDetailLinks({ ...detail, sessionId: null }), []);
});

test("a run's history links a person's decision to the approval it was taken on", () => {
  const events = [
    { id: "e1", kind: "decision", node_id: "n1", actor_id: "u1", created_at: null, detail: { action: "approved" } },
    { id: "e2", kind: "decision", node_id: "n2", actor_id: "u1", created_at: null, detail: { action: "confirmed" } },
  ];
  const decisions = [
    { id: "d2", node_id: "n2", action: "confirmed", approval_id: null, decided_by: "u1" },
    { id: "d1", node_id: "n1", action: "approved", approval_id: "ap1", decided_by: "u1" },
  ];
  const history = runHistory(events, [], () => "", decisions);
  assert.deepEqual(history.map((entry) => entry.approvalId), ["ap1", undefined]);
  assert.equal(runHistory(events, [], () => "")[0].approvalId, undefined, "without decisions nothing is linked");
});

test("one title everywhere: the server's words, a REST request's own title, the subtitle as why", () => {
  const legacy = { title: "Execute tool run_cli_command", toolName: "run_cli_command", details: ["rule: require_for_tools"] };
  const served = { title: "Run a command on the Octryx server", subtitle: "This tool needs approval in this Workspace" };
  assert.deepEqual(approvalTexts(served, legacy), served,
    "the stored 'Execute tool …' is never the title");
  const plan = { kind: "write_plan", plan_id: "p1", writes: [{ index: 0, tool: "create_jira_ticket", fields: {} }] };
  assert.equal(approvalTexts({ title: "Write plan with 1 write" }, plan).title, "Write plan with 1 write");
  // A REST write names its request, which says more than "Send a request to Desk".
  assert.equal(approvalTexts({ title: "Send a request to Desk", subtitle: "Why" }, DETAIL.payload).title,
    "POST /tickets");
  // The preview's own title is never the title: the server words every approval.
  assert.deepEqual(approvalTexts({ title: "Run a command" }, { title: "Run git status" }), { title: "Run a command", subtitle: "" });
  assert.equal(approvalTexts(null, null).title, "Approval");
});
