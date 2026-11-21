// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Workflow clarification decisions: the options come from the structured
// `decision_request` of the turn execution summary and the chosen value is
// sent as `workflow_decisions`; nothing is parsed from message text.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import {
  buildWorkflowDecisionSend,
  workflowDecisionsBody,
} from "../../src/chat/run/workflowDecisionSend.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const DECISIONS_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/workflow_contracts/decisions.py", import.meta.url),
  "utf8",
).replace(/\r\n/g, "\n");

// value -> label pairs of one decision's fixed button labels in the backend catalog.
function backendOptionLabels(decisionConstant) {
  const catalog = DECISIONS_SOURCE.indexOf("WORKFLOW_DECISION_OPTION_LABELS");
  const start = DECISIONS_SOURCE.indexOf(`\n    ${decisionConstant}: {`, catalog);
  assert.ok(start > catalog, `${decisionConstant} is missing from the label catalog`);
  const body = DECISIONS_SOURCE.slice(start, DECISIONS_SOURCE.indexOf("\n    },", start));
  const constants = Object.fromEntries(
    [...DECISIONS_SOURCE.matchAll(/^([A-Z_]+) = "([a-z_]+)"$/gm)].map((m) => [m[1], m[2]]),
  );
  return [...body.matchAll(/^\s{8}([A-Z_]+): "([^"]+)",$/gm)].map((m) => ({
    value: constants[m[1]],
    label: m[2],
  }));
}

function decisionSummary(decisionRequest) {
  return parseTurnExecutionSummary(
    buildSummaryFixture({
      traceId: "trace-1",
      sessionId: "session-1",
      reasonCode: "workflow_decision_requested",
      decisionRequest,
    }),
  );
}

test("the capability escalation decision offers exactly allow or stay read-only", () => {
  const options = backendOptionLabels("CAPABILITY_ESCALATION_DECISION");
  assert.deepEqual(options, [
    { value: "allow_changes", label: "Allow changes in this session" },
    { value: "stay_read_only", label: "Stay read-only" },
  ]);
  const parsed = decisionSummary({ decision_key: "capability_escalation", options, recorded_value: null });
  assert.equal(parsed.state, "needs_clarification");
  assert.deepEqual(parsed.decisionRequest, {
    decisionKey: "capability_escalation",
    options,
    recordedValue: null,
  });
});

test("malformed decision requests render no buttons", () => {
  for (const raw of [
    null,
    "capability_escalation",
    { decision_key: "Capability Escalation", options: [{ value: "a", label: "A" }] },
    { decision_key: "capability_escalation", options: [] },
    { decision_key: "capability_escalation", options: [{ value: "rm -rf /", label: "x" }] },
  ]) {
    assert.equal(decisionSummary(raw).decisionRequest, null, JSON.stringify(raw));
  }
  const unknownRecorded = decisionSummary({
    decision_key: "capability_escalation",
    options: [{ value: "allow_changes", label: "Allow changes in this session" }],
    recorded_value: "something_else",
  });
  assert.equal(unknownRecorded.decisionRequest.recordedValue, null);
});

test("a chosen option is sent as the structured workflow_decisions field", () => {
  const { prompt, options } = buildWorkflowDecisionSend({
    decisionKey: "capability_escalation",
    value: "allow_changes",
    label: "Allow changes in this session",
  });
  assert.equal(prompt, "Decision: Allow changes in this session");
  assert.deepEqual(workflowDecisionsBody(options), {
    workflow_decisions: { capability_escalation: "allow_changes" },
  });
  assert.deepEqual(workflowDecisionsBody(undefined), {});
  assert.deepEqual(workflowDecisionsBody({ workflowDecisions: {} }), {});
});
