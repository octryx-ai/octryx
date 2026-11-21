// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  TURN_EXECUTION_REFRESH_EVENT,
  emitTurnExecutionRefresh,
  shouldRefreshTurnExecutionSummary,
  subscribeTurnExecutionRefresh,
} from "../../src/chat/run/turnExecutionRefreshSignal.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

function ready(reasonCode, sessionId = "session-1") {
  return {
    status: "ready",
    summary: parseTurnExecutionSummary(
      buildSummaryFixture({ traceId: "trace-1", sessionId, reasonCode }),
    ),
  };
}

test("subscribers receive session refresh signals until they unsubscribe", () => {
  const target = new EventTarget();
  const received = [];
  const unsubscribe = subscribeTurnExecutionRefresh((detail) => received.push(detail), target);
  emitTurnExecutionRefresh("session-1", target);
  unsubscribe();
  emitTurnExecutionRefresh("session-2", target);
  assert.deepEqual(received, [{ sessionId: "session-1" }]);
});

test("malformed refresh events are ignored", () => {
  const target = new EventTarget();
  const received = [];
  subscribeTurnExecutionRefresh((detail) => received.push(detail), target);
  target.dispatchEvent(new CustomEvent(TURN_EXECUTION_REFRESH_EVENT));
  target.dispatchEvent(new CustomEvent(TURN_EXECUTION_REFRESH_EVENT, { detail: { sessionId: 7 } }));
  target.dispatchEvent(new CustomEvent(TURN_EXECUTION_REFRESH_EVENT, { detail: { sessionId: "" } }));
  assert.deepEqual(received, []);
});

test("pending and changeable unknown summaries of the same session refresh", () => {
  for (const reasonCode of ["approval_pending", "approval_state_unknown", "runtime_outcome_unknown"]) {
    assert.equal(shouldRefreshTurnExecutionSummary(ready(reasonCode), "session-1"), true, reasonCode);
  }
});

test("settled summaries, other sessions and non-ready loads do not refresh", () => {
  for (const reasonCode of [
    "runtime_finished",
    "runtime_failed",
    "runtime_cancelled",
    "gate_denied",
    "gate_needs_approval",
    "gate_needs_configuration",
    "gate_needs_clarification",
    "gate_blocked_unknown",
    "model_alias_not_admitted",
    "model_data_policy_denied",
    "intermediate_trace",
    "missing_snapshot",
    "malformed_snapshot",
    "inconsistent_snapshot",
  ]) {
    assert.equal(shouldRefreshTurnExecutionSummary(ready(reasonCode), "session-1"), false, reasonCode);
  }
  assert.equal(shouldRefreshTurnExecutionSummary(ready("approval_pending", "session-2"), "session-1"), false);
  for (const load of [
    { status: "idle" },
    { status: "loading" },
    { status: "error" },
    { status: "unavailable", reason: "not_found" },
  ]) {
    assert.equal(shouldRefreshTurnExecutionSummary(load, "session-1"), false, load.status);
  }
});

test("an unrecognized state refreshes instead of being treated as settled", () => {
  const load = ready("runtime_finished");
  load.summary.state = { unrecognized: true, raw: "resuming" };
  assert.equal(shouldRefreshTurnExecutionSummary(load, "session-1"), true);
});
