// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Turns in the chat: which actions a tool approval card offers, where the route
// banner takes its text from, and how the turn summary names an approval.
import assert from "node:assert/strict";
import { test } from "node:test";

import { approvalCardModel } from "../../src/chat/approvalCardActions.ts";
import { buildRoutingSummary } from "../../src/chat/routingExplainability.ts";
import {
  parseTurnExecutionSummary,
  turnApprovalLabel,
} from "../../src/chat/run/turnExecutionSummaryParse.ts";

// The route explanation left the bar above the composer; it stays in the header's route chip.
const buildRoutingNotice = ({ selectedSession }) => {
  const { label, detail } = buildRoutingSummary({ selectedSession, workspaceLabel: "", runtimeLabel: "" });
  return `${label}. ${detail}`;
};

const kinds = (model) => model.actions.map((action) => `${action.kind}:${action.label}`);

test("a tool approval offers Deny, Retry from here and Allow once", () => {
  const tool = { id: "appr-2", status: "pending", action: "terraform_apply" };
  assert.deepEqual(kinds(approvalCardModel(tool, { canRetry: true })), [
    "reject:Deny",
    "retry:Retry from here",
    "approve:Allow once",
  ]);
  assert.deepEqual(kinds(approvalCardModel(tool, { canRetry: false })), ["reject:Deny", "approve:Allow once"]);
  const decided = approvalCardModel({ ...tool, status: "rejected" }, { canRetry: true });
  assert.deepEqual(kinds(decided), ["retry:Retry from here"]);
  assert.equal(approvalCardModel({ ...tool, status: "rejected" }, { canRetry: false }).statusLabel, "Denied");
  assert.equal(approvalCardModel({ ...tool, status: "expired" }, { canRetry: false }).statusLabel, "Timed out");
});

function session(overrides = {}) {
  return {
    id: "s-1",
    title: "t",
    status: "active",
    projectName: "default",
    runtimeTargetId: "",
    runtimeLabel: "Automatic",
    startedAt: null,
    agentType: "diagnosis",
    routingIntent: "diagnosis",
    routingReason: "intent:diagnosis_default",
    ...overrides,
  };
}

test("the route chip keeps the session's routing explanation", () => {
  const notice = buildRoutingNotice({ selectedSession: session() });
  assert.match(notice, /^Route · Diagnosis\./);
  assert.match(notice, /Task wording matched Diagnosis Default/);
  assert.match(notice, /Mode, agent group, and agent remain policy-derived/);
});

test("the turn summary names an approval by its tool", () => {
  const summary = parseTurnExecutionSummary({
    version: "turn_execution_summary.v1",
    state: "waiting_approval",
    approvals: [
      { approval_id: "a-2", tool_name: "terraform_apply", status: "approved" },
      { approval_id: "a-3", tool_name: null, status: "pending" },
    ],
  });
  assert.deepEqual(summary.approvals.map(turnApprovalLabel), ["terraform_apply", "Approval"]);
});
