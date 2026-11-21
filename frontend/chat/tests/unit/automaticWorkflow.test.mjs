// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The composer's only visible state is "Automatic"; the explicit choice is
// made in the same single workflow pill; the send payload never carries `agent_type`;
// a held proposal is answered inline (Allow once / Deny) on its one
// approval record.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
import {
  AUTOMATIC_LABEL,
  automaticWorkflowChip,
  isWorkflowProposalApproval,
  PROPOSAL_ANSWERS,
  WORKFLOW_PROPOSAL_APPROVAL_PREFIX,
  workflowChipText,
} from "../../src/chat/composer/automaticWorkflow.ts";
import { buildWorkflowProposalDecision } from "../../src/chat/run/workflowDecisionSend.ts";

const APPROVAL_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/workflow_routing/proposal_approval.py", import.meta.url),
  "utf8",
);

const AUTOMATIC_SELECTION = {
  sessionId: "",
  projectId: "p-1",
  runtimeTargetId: "",
  thinkingLevel: "light",
  routingOverridesEnabled: false,
  agentId: "",
  workflowKey: "",
};

function proposal(overrides = {}) {
  return {
    proposalId: "p1",
    status: "needs_confirmation",
    reasonCode: null,
    workflowKey: "knowledge-request-routing",
    workflowTitle: "Knowledge request",
    confidence: "high",
    reason: "A documented version change is asked.",
    changeCapable: false,
    decision: null,
    ...overrides,
  };
}

test("the default mode is Automatic and there is exactly one workflow control", () => {
  const pill = readFileSync(new URL("../../src/chat/composer/ModeOfWorkPill.tsx", import.meta.url), "utf8");
  assert.equal((pill.match(/<select/g) || []).length, 1);
  assert.equal(pill.includes("composer-advanced-toggle"), false);
  assert.equal(pill.includes("aria-expanded"), false);
  assert.equal(pill.includes("composer-workflow-chip__text"), false);
  assert.deepEqual(automaticWorkflowChip({}), { state: "automatic", label: AUTOMATIC_LABEL, detail: null });
  assert.equal(AUTOMATIC_LABEL, "Automatic");
});

test("the send payload carries no agent_type, also not with an explicit agent or workflow", () => {
  const automatic = buildChatSendBody("Was hat sich geändert?", AUTOMATIC_SELECTION);
  assert.equal("agent_type" in automatic, false);
  assert.equal(automatic.workflow_key, "");
  assert.equal(automatic.agent_id, "");

  const explicitAgent = buildChatSendBody("x", {
    ...AUTOMATIC_SELECTION,
    routingOverridesEnabled: true,
    agentId: "agent-1",
  });
  assert.equal("agent_type" in explicitAgent, false);
  assert.equal(explicitAgent.agent_id, "agent-1");

  const advanced = buildChatSendBody("x", { ...AUTOMATIC_SELECTION, workflowKey: "coding-change-tdd" });
  assert.equal("agent_type" in advanced, false);
  assert.equal(advanced.workflow_key, "coding-change-tdd");
});

test("the chip shows what was suggested, with its reason", () => {
  const suggested = automaticWorkflowChip({ proposal: proposal() });
  assert.equal(workflowChipText(suggested), "Suggested: Knowledge request: A documented version change is asked.");
  const pending = automaticWorkflowChip({ proposal: proposal({ reason: null }) });
  assert.equal(workflowChipText(pending), "Suggested: Knowledge request");
  const phased = automaticWorkflowChip({ proposal: proposal({ phased: true }) });
  assert.equal(workflowChipText(phased), "Knowledge request · waits for Start");
  const answered = automaticWorkflowChip({ proposal: proposal({ decision: "skip" }) });
  assert.equal(answered.state, "automatic");
  const offered = automaticWorkflowChip({ proposal: proposal({ status: "offered" }) });
  assert.equal(offered.state, "automatic");
  const advanced = automaticWorkflowChip({ selectedWorkflowTitle: "Coding change", proposal: proposal() });
  assert.equal(workflowChipText(advanced), "Coding change");
});

test("a held proposal is answered inline on its one approval record", () => {
  assert.deepEqual(PROPOSAL_ANSWERS.map((answer) => answer.label), ["Allow once", "Deny"]);
  assert.deepEqual(PROPOSAL_ANSWERS.map((answer) => answer.value), ["apply", "skip"]);
  assert.ok(APPROVAL_SOURCE.includes(`PROPOSAL_APPROVAL_ACTION_PREFIX = "${WORKFLOW_PROPOSAL_APPROVAL_PREFIX}"`));
  assert.equal(isWorkflowProposalApproval({ action: `${WORKFLOW_PROPOSAL_APPROVAL_PREFIX}${"a".repeat(32)}` }), true);
  assert.equal(isWorkflowProposalApproval({ action: "Approve write for edit_workspace_file" }), false);
  assert.deepEqual(
    buildWorkflowProposalDecision("s-1", { decisionKey: "workflow_proposal", value: "skip", label: "x", proposalId: "p1" }),
    { path: "/chat/api/sessions/s-1/workflow-proposal", body: { proposal_id: "p1", decision: "skip" } },
  );
  assert.equal(
    buildWorkflowProposalDecision("s-1", { decisionKey: "workflow_proposal", value: "always", label: "x", proposalId: "p1" }),
    null,
    "a standing confirmation is no answer to a workflow proposal",
  );
});
