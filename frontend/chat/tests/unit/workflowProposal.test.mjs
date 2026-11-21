// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Workflow proposals: the summary carries closed proposal fields only,
// the proposal statuses equal the backend vocabulary, and an answer goes to
// the proposal endpoint instead of being sent as a new message.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { WORKFLOW_PROPOSAL_STATUSES } from "../../src/chat/run/turnExecutionSummary.types.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import {
  buildOfferedWorkflowSend,
  buildWorkflowProposalDecision,
  RUN_OFFERED_WORKFLOW,
} from "../../src/chat/run/workflowDecisionSend.ts";
import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
import { buildSummaryFixture, profileSection } from "../e2e/turnExecutionSummaryFixtures.mjs";

const STATES_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/workflow_routing/proposal_states.py", import.meta.url),
  "utf8",
).replace(/\r\n/g, "\n");

function pendingSummary(workflowProposal) {
  return parseTurnExecutionSummary(
    buildSummaryFixture({
      traceId: "trace-1",
      sessionId: "session-1",
      reasonCode: "gate_needs_confirmation",
      profile: {
        ...profileSection({ profileId: "direct_chat_safe", status: "allowed", decisionSource: null }),
        gate: { outcome: "blocked", status: "needs_confirmation", decision_source: "workflow_proposal" },
      },
      workflowProposal,
    }),
  );
}

test("proposal statuses equal the backend vocabulary", () => {
  const backend = [...STATES_SOURCE.matchAll(/^STATUS_[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1]);
  assert.deepEqual([...WORKFLOW_PROPOSAL_STATUSES].sort(), backend.sort());
});

test("a pending proposal parses to closed fields and drops anything else", () => {
  const summary = pendingSummary({
    status: "needs_confirmation",
    reason_code: "workflow_run_required",
    proposal_id: "abc123",
    workflow_key: "spring-boot-4-upgrade",
    workflow_title: "Spring Boot 4 upgrade",
    confidence: "high",
    change_capable: true,
    reason: "must never be read from the summary",
  });
  assert.equal(summary.state, "needs_confirmation");
  assert.equal(summary.nextAction.kind, "confirm_workflow_proposal");
  assert.deepEqual(summary.workflowProposal, {
    status: "needs_confirmation",
    reasonCode: "workflow_run_required",
    proposalId: "abc123",
    workflowKey: "spring-boot-4-upgrade",
    workflowTitle: "Spring Boot 4 upgrade",
    confidence: "high",
    changeCapable: true,
  });
  assert.equal(pendingSummary(null).workflowProposal, null);
  assert.deepEqual(pendingSummary({ status: "guessed" }).workflowProposal.status, {
    unrecognized: true,
    raw: "guessed",
  });
});

test("an answer targets the proposal endpoint, a plain decision does not", () => {
  const apply = buildWorkflowProposalDecision("session 1", {
    decisionKey: "workflow_proposal",
    value: "apply",
    label: "Apply",
    proposalId: "abc123",
  });
  assert.deepEqual(apply, {
    path: "/chat/api/sessions/session%201/workflow-proposal",
    body: { proposal_id: "abc123", decision: "apply" },
  });
  const plain = { decisionKey: "capability_escalation", value: "allow_changes", label: "Allow changes" };
  assert.equal(buildWorkflowProposalDecision("session-1", plain), null);
  assert.equal(
    buildWorkflowProposalDecision("session-1", { ...plain, proposalId: "abc123", value: "maybe" }),
    null,
  );
  assert.equal(buildWorkflowProposalDecision(null, { ...plain, proposalId: "abc123", value: "skip" }), null);
});

// An unasked proposal is an offer next to the answer.
// Accepting it sends the turn's own message again with the workflow selected.
test("an accepted offer re-sends the message with the workflow, nothing else does", () => {
  const offered = buildOfferedWorkflowSend({
    decisionKey: "workflow_offer",
    value: RUN_OFFERED_WORKFLOW,
    label: "Run with workflow: Spec",
    workflowKey: "spec-writing",
    prompt: "Write the spec.",
  });
  assert.deepEqual(offered, { prompt: "Write the spec.", options: { workflowKey: "spec-writing" } });
  assert.equal(buildOfferedWorkflowSend({ decisionKey: "x", value: "apply", label: "x" }), null);
  const body = buildChatSendBody(
    offered.prompt,
    {
      sessionId: "s",
      projectId: "p",
      runtimeTargetId: "",
      thinkingLevel: "light",
      routingOverridesEnabled: false,
      agentId: "",
      workflowKey: "",
    },
    offered.options,
  );
  assert.equal(body.workflow_key, "spec-writing");
});
