// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import {
  presentNextAction,
  presentRunCapability,
  presentTurnExecutionState,
  shouldShowTurnExecutionCard,
} from "../../src/chat/run/turnExecutionSummaryPresentation.ts";
import { TURN_EXECUTION_STATES } from "../../src/chat/run/turnExecutionSummary.types.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const CLOSED_STATES = {
  finished_unverified: ["neutral", "Finished, unverified"],
  denied: ["blocked", "Denied"],
  needs_approval: ["attention", "Needs approval"],
  needs_configuration: ["attention", "Needs configuration"],
  needs_clarification: ["attention", "Needs clarification"],
  blocked_unknown: ["blocked", "Blocked"],
  waiting_approval: ["attention", "Waiting for approval"],
  failed: ["error", "Failed"],
  cancelled: ["neutral", "Cancelled"],
  unknown: ["neutral", "Status unknown"],
};

function summaryPayload(overrides = {}) {
  return {
    ...buildSummaryFixture({
      traceId: "trace-1",
      sessionId: "session-1",
      reasonCode: "runtime_finished",
      model: { provider: "bedrock", model: "nova" },
      usage: { tokens_in: 1, tokens_out: 2 },
    }),
    ...overrides,
  };
}

test("every closed state maps to its tone and label", () => {
  for (const [state, [tone, label]] of Object.entries(CLOSED_STATES)) {
    const presentation = presentTurnExecutionState(state);
    assert.equal(presentation.tone, tone, state);
    assert.equal(presentation.label, label, state);
  }
});

test("no closed state maps to the success tone", () => {
  for (const state of TURN_EXECUTION_STATES) {
    assert.notEqual(presentTurnExecutionState(state).tone, "success", state);
  }
  assert.equal(presentTurnExecutionState("finished_unverified").tone, "neutral");
});

test("unknown and malformed states render as neutral unrecognized", () => {
  for (const value of ["completed", "verified", "passed", "success", "", null, undefined, 42, {}, "__proto__", "toString"]) {
    const presentation = presentTurnExecutionState(value);
    assert.equal(presentation.tone, "neutral", String(value));
    assert.equal(presentation.label, "Unrecognized status", String(value));
  }
});

test("next action: none hides, server label wins, unknown kind is neutral", () => {
  assert.equal(presentNextAction({ kind: "none", label: null }), null);
  assert.equal(
    presentNextAction({ kind: "complete_configuration", label: "Select a runtime" }),
    "Select a runtime",
  );
  assert.equal(
    presentNextAction({ kind: "complete_configuration", label: null }),
    "Complete the required configuration",
  );
  assert.equal(
    presentNextAction({ kind: { unrecognized: true, raw: "launch" }, label: null }),
    "Unrecognized next action",
  );
});

test("parser keeps closed states and marks unknown states unrecognized", () => {
  const blocked = parseTurnExecutionSummary(summaryPayload({ state: "needs_configuration" }));
  assert.equal(blocked.state, "needs_configuration");
  const unknown = parseTurnExecutionSummary(summaryPayload({ state: "verified" }));
  assert.deepEqual(unknown.state, { unrecognized: true, raw: "verified" });
  assert.equal(presentTurnExecutionState(unknown.state).label, "Unrecognized status");
});

test("parser rejects unsupported versions and non-objects", () => {
  assert.equal(parseTurnExecutionSummary(summaryPayload({ version: "turn_execution_summary.v2" })), null);
  assert.equal(parseTurnExecutionSummary(null), null);
  assert.equal(parseTurnExecutionSummary([]), null);
});

test("parser drops non-allow-listed fields and bounds lists and text", () => {
  const parsed = parseTurnExecutionSummary(
    summaryPayload({
      input_messages: [{ role: "user", content: "secret prompt" }],
      state_reason: { code: "runtime_finished", source: "runtime", text: "y".repeat(1000) },
      capabilities_used: Array.from({ length: 80 }, (_, index) => ({
        name: `tool_${index}`,
        calls: 1,
        succeeded: 1,
        failed: 0,
        arguments: { token: "secret" },
      })),
      execution_profile: { profile_id: "p1", status: "allowed", policy: { raw: true } },
    }),
  );
  const serialized = JSON.stringify(parsed);
  assert.ok(!serialized.includes("secret"));
  assert.ok(!serialized.includes("policy"));
  assert.equal(parsed.capabilitiesUsed.length, 50);
  assert.equal(parsed.capabilitiesUsed[0].calls, 1);
  assert.ok(parsed.stateReason.text.length <= 280);
  assert.equal(parsed.executionProfile.profileId, "p1");
});

test("run capability from the workflow is parsed and presented with its escalation", () => {
  const parsed = parseTurnExecutionSummary(
    summaryPayload({
      execution_profile: {
        profile_id: "p1",
        status: "allowed",
        capability: { class: "change", source: "chat_default", enforced: true, escalated: true, reason: "x" },
      },
    }),
  );
  assert.deepEqual(parsed.executionProfile.runCapability, {
    capabilityClass: "change",
    source: "chat_default",
    enforced: true,
    escalated: true,
    agentTypeIgnored: false,
  });
  assert.equal(presentRunCapability(parsed.executionProfile.runCapability), "Change (raised by your decision)");
  assert.equal(presentRunCapability(null), null);
});

test("a trace without snapshot stays unknown with no invented profile", () => {
  const parsed = parseTurnExecutionSummary(
    buildSummaryFixture({
      traceId: "trace-no-snapshot",
      sessionId: "session-1",
      reasonCode: "missing_snapshot",
    }),
  );
  assert.equal(parsed.state, "unknown");
  assert.equal(parsed.stateReason.source, "trace");
  assert.equal(parsed.executionProfile, null);
  assert.equal(presentTurnExecutionState(parsed.state).label, "Status unknown");
});

test("status card is hidden for idle loads and intermediate traces only", () => {
  const ready = (reasonCode) => ({
    status: "ready",
    summary: parseTurnExecutionSummary(
      buildSummaryFixture({ traceId: "trace-1", sessionId: "session-1", reasonCode }),
    ),
  });
  assert.equal(shouldShowTurnExecutionCard({ status: "idle" }), false);
  assert.equal(shouldShowTurnExecutionCard(ready("intermediate_trace")), false);
  for (const reasonCode of [
    "approval_pending",
    "clarification_requested",
    "runtime_outcome_unknown",
    "missing_snapshot",
    "runtime_finished",
  ]) {
    assert.equal(shouldShowTurnExecutionCard(ready(reasonCode)), true, reasonCode);
  }
  for (const load of [
    { status: "loading" },
    { status: "error" },
    { status: "unavailable", reason: "not_found" },
  ]) {
    assert.equal(shouldShowTurnExecutionCard(load), true, load.status);
  }
});
