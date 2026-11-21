// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/phoneApprovals.test.mjs
//
// Approvals on the phone (backend): GET /api/v1/approvals/decidable becomes cards with the preview's title, the
// phone offers only "Allow once" and "Deny" out of `offered_decisions` (never "Always"), an approval card replaces the
// attention entry about the same approval or its run's gate, and every refusal reads as words.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  approvalOfItem,
  bodyRows,
  decisionErrorText,
  decisionOutcome,
  phoneApprovalLink,
  phoneDecisions,
  readDecidable,
  settledByRefusal,
  withoutApprovals,
} from "../../src/mobile/phoneApprovals.ts";

// The shape the backend sends for a central REST write (rest_connector/preview.py, masked since).
const REST = {
  id: "a-rest", action: "Approve tool execution for rest__desk__create_ticket", status: "pending",
  session_id: "s-flow", task_run_id: null, requested_by: "u1", created_at: "2026-11-15T10:00:00",
  payload: {
    kind: "tool_execution", toolName: "rest__desk__create_ticket", title: "Create ticket",
    details: [
      "request: POST http://127.0.0.1:8878/tickets", "api: Demo Tickets Desk", "operation: create_ticket",
      "connection: Desk (local)", "headers: X-Request-Source",
      'body: {"title": "Nightly stock sync failed", "priority": 1, "api_token": "[redacted]", "requester": {"email": "anna@demo-shop.example"}}',
    ],
  },
  offered_decisions: ["once", "deny"], decision_note: null, requested_by_name: "Anna", approved_by_name: null,
  workspace_id: "shop", workflow_run_id: "run-7",
};
const CHAT = {
  id: "a-cli", action: "Approve tool execution for run_cli_command", status: "pending", session_id: "s-chat",
  title: "Run git status", payload: { title: "Run git status", command: "git status", toolName: "run_cli_command" },
  offered_decisions: ["once", "always", "deny"], workspace_id: "shop", workflow_run_id: null,
};

test("a decidable item becomes a card titled by the server, with where it was asked", () => {
  const [rest, chat, ...rest_] = readDecidable({ items: [REST, CHAT, { id: "decided", status: "approved" }, { nope: 1 }], count: 4 });
  assert.equal(rest_.length, 0, "decided and broken items are not listed");
  assert.equal(rest.title, "POST /tickets on Demo Tickets Desk › create_ticket");
  assert.equal(rest.preview, "rest");
  assert.equal(rest.workspaceId, "shop");
  assert.equal(rest.requestedByName, "Anna");
  assert.deepEqual(phoneApprovalLink(rest), { kind: "run", runId: "run-7" });
  assert.equal(chat.title, "Run git status");
  assert.equal(rest.createdAt, "2026-11-15T10:00:00Z", "the server's zoneless time is UTC");
  assert.equal(chat.preview, "generic");
  assert.deepEqual(phoneApprovalLink(chat), { kind: "chat", sessionId: "s-chat" });
  assert.equal(phoneApprovalLink({ sessionId: null, workflowRunId: null }), null);
  assert.deepEqual(readDecidable(null), []);
});

test("the title and why come from the server; a REST write keeps its request as the title", () => {
  // An approval stored before: the preview still says "Execute tool …", the server words it on the way out.
  const [gate, rest] = readDecidable({ items: [
    { ...CHAT, title: "Run a command on the Octryx server", subtitle: "This tool needs approval in this Workspace",
      details: ["It changes data"], payload: { title: "Execute tool run_cli_command", toolName: "run_cli_command", details: ["risk: write"] } },
    { ...REST, title: "Create ticket", subtitle: "No person started this run; its write to Demo Tickets Desk needs your approval" },
  ] });
  assert.equal(gate.title, "Run a command on the Octryx server");
  assert.equal(gate.subtitle, "This tool needs approval in this Workspace");
  assert.deepEqual(gate.details, ["It changes data"], "the served lines, not the stored 'risk: write'");
  assert.equal(rest.title, "POST /tickets on Demo Tickets Desk › create_ticket", "the request says more than the sentence");
  assert.match(rest.subtitle, /^No person started this run/);
  assert.equal(readDecidable({ items: [CHAT] })[0].subtitle, "", "no subtitle served, none shown");
});

test("a governance review is shown read-only: no buttons, whatever the server offers", () => {
  const [review] = readDecidable({ items: [{ ...CHAT, id: "a-gov", session_id: null, task_run_id: null, kind: "governance" }] });
  assert.equal(review.governance, true);
  assert.deepEqual(review.decisions, []);
  const [chat] = readDecidable({ items: [CHAT] });
  assert.equal(chat.governance, false);
  assert.ok(chat.decisions.length > 0);
});

test("the phone offers only Allow once and Deny, and only what the server offers; Always never", () => {
  const kinds = (offered) => phoneDecisions(offered).map((action) => action.label);
  assert.deepEqual(kinds(["once", "always", "deny"]), ["Deny", "Allow once"]);
  assert.deepEqual(kinds(["deny"]), ["Deny"]);
  assert.deepEqual(kinds(["always"]), [], "an approval only the web can decide gets no phone buttons");
  assert.deepEqual(kinds([]), []);
  assert.deepEqual(kinds(undefined), [], "nothing offered: no buttons");
  assert.deepEqual(readDecidable({ items: [CHAT] })[0].decisions.map((action) => action.kind), ["reject", "approve"]);
  // A write plan reads as Reject and Approve, as in the chat; still only what is offered.
  assert.deepEqual(phoneDecisions(["once", "deny"], "plan").map((action) => action.label), ["Reject", "Approve"]);
});

test("an approval card replaces its chat entry and its run's gate; other needs stay", () => {
  const approvals = readDecidable({ items: [REST, CHAT] });
  const item = (key, kind, id, runId = null) => ({ key, kind, id, runId });
  const needs = [
    item("tool_approval:a-cli", "gate", "a-cli"),
    item("run:run-7:t", "gate", "run-7", "run-7"),
    item("run:run-9:t", "gate", "run-9", "run-9"),
    item("question:q1", "question", "q1", "run-7"),
    item("device_approval:d1", "device_approval", "d1"),
  ];
  assert.deepEqual(withoutApprovals(needs, approvals).map((entry) => entry.key), [
    "run:run-9:t", "question:q1", "device_approval:d1",
  ]);
  assert.equal(withoutApprovals(needs, []).length, needs.length);
  // A notification for the chat's tool approval opens the approval card.
  assert.equal(approvalOfItem("tool_approval:a-cli", approvals)?.id, "a-cli");
  assert.equal(approvalOfItem("run:run-7:t", approvals), null);
});

test("the body reads as rows; nested values fold as JSON; masked values stay masked", () => {
  const rows = bodyRows([
    { key: "title", label: "Title", value: "Nightly stock sync failed" },
    { key: "api_token", label: "Api token", value: "[redacted]" },
    { key: "requester", label: "Requester", value: '{"email":"anna@demo-shop.example"}' },
    { key: "note", label: "Note", value: "{not json" },
  ]);
  assert.deepEqual(rows.map((row) => row.json === null), [true, true, false, true]);
  assert.equal(rows[1].value, "[redacted]");
  assert.equal(rows[2].json, '{\n  "email": "anna@demo-shop.example"\n}');
});

test("refusals and outcomes read as words", () => {
  assert.equal(decisionErrorText("approve", 403), "You may not decide this approval.");
  assert.equal(decisionErrorText("reject", 404), "This approval no longer exists or is not visible to you.");
  assert.equal(decisionErrorText("approve", 409), "This approval is no longer waiting: its time ran out.");
  assert.equal(
    decisionErrorText("reject", 409, "This approval was already decided.", "approval_already_resolved"),
    "This approval was already decided.",
  );
  assert.match(decisionErrorText("approve", 0), /did not reach Octryx/);
  assert.ok([403, 404, 409].every(settledByRefusal) && !settledByRefusal(500), "a refusal that settles it reloads the list");
  assert.match(decisionOutcome("approve"), /^Allowed once\./);
  assert.equal(decisionOutcome("reject", "  Not tonight "), "Denied. Your reason goes with it: “Not tonight”");
  assert.equal(decisionOutcome("reject"), "Denied. Octryx does not run this request.");
  assert.match(decisionOutcome("approve", "", "plan"), /^Approved\. The writes in this plan run without asking again/);
});
