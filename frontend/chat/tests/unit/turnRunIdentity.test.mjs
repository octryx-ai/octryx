// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Run/Attempt identity of `turn_execution_summary.v1`: the typed
// parse, its neutral fallbacks, the no-success tone rule, and drift guards
// against the backend closed sets (backend source is read, never executed).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import {
  TURN_RUN_END_REASONS,
  TURN_RUN_IDENTITY_KINDS,
  TURN_RUN_STATES,
  parseTurnRunIdentity,
} from "../../src/chat/run/turnRunIdentityParse.ts";
import {
  presentEndReason,
  presentRunState,
  shortRunId,
} from "../../src/chat/run/turnRunIdentityPresentation.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const RUN_ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const ATTEMPT_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";
const NO_RUN = { runId: null, runState: null, attempt: null };

function productRun(overrides = {}, attempt = {}) {
  return {
    kind: "product_run",
    product_run_id: RUN_ID,
    run_state: "finished_unverified",
    attempt: { id: ATTEMPT_ID, number: 1, state: "finished_unverified", end_reason: "runtime_finished", ...attempt },
    ...overrides,
  };
}

test("a resolved product run parses into typed identity", () => {
  assert.deepEqual(parseTurnRunIdentity(productRun()), {
    kind: "product_run",
    runId: RUN_ID,
    runState: "finished_unverified",
    attempt: { id: ATTEMPT_ID, number: 1, state: "finished_unverified", endReason: "runtime_finished" },
  });
  assert.equal(parseTurnRunIdentity(productRun({}, { end_reason: null })).attempt.endReason, null);
});

test("runless kinds keep their kind and carry no ids", () => {
  for (const kind of ["compat_turn", "unscoped_turn", "unresolved"]) {
    assert.deepEqual(parseTurnRunIdentity({ kind, product_run_id: null, run_state: null, attempt: null }), {
      kind,
      ...NO_RUN,
    });
  }
});

test("unknown kinds and broken product runs become neutral unresolved", () => {
  const broken = [
    undefined,
    null,
    "product_run",
    { kind: "completed_run" },
    { kind: "PRODUCT_RUN" },
    productRun({ product_run_id: "not-a-uuid" }),
    productRun({ product_run_id: RUN_ID.toUpperCase() }),
    productRun({ attempt: null }),
    productRun({}, { id: "x" }),
    productRun({}, { number: 0 }),
    productRun({}, { number: 1.5 }),
    productRun({}, { number: "1" }),
  ];
  for (const value of broken) {
    assert.deepEqual(parseTurnRunIdentity(value), { kind: "unresolved", ...NO_RUN }, JSON.stringify(value));
  }
});

test("reserved and unknown states are unrecognized and never a success tone", () => {
  for (const reserved of ["verifying", "passed", "success"]) {
    const parsed = parseTurnRunIdentity(productRun({ run_state: reserved }, { state: reserved, end_reason: reserved }));
    assert.equal(parsed.runState.unrecognized, true, reserved);
    assert.equal(parsed.attempt.state.unrecognized, true, reserved);
    assert.equal(presentRunState(parsed.attempt.state).tone, "neutral");
    assert.equal(presentEndReason(parsed.attempt.endReason), "unrecognized");
  }
  const tones = new Set(TURN_RUN_STATES.map((state) => presentRunState(state).tone));
  assert.deepEqual([...tones].sort(), ["attention", "blocked", "error", "neutral", "running", "success"]);
  // ``completed`` is reserved; nothing else is success.
  for (const state of TURN_RUN_STATES) {
    assert.equal(presentRunState(state).tone === "success", state === "completed", state);
  }
  assert.equal(presentRunState("finished_unverified").tone, "neutral");
  assert.equal(presentRunState("failed").tone, "error");
  assert.equal(shortRunId(RUN_ID), "0f8fad5b");
});

test("the summary parser carries the identity and drops unexpected fields", () => {
  const payload = buildSummaryFixture({ traceId: "t", sessionId: "s", reasonCode: "runtime_finished" });
  assert.deepEqual(parseTurnExecutionSummary(payload).runIdentity, { kind: "compat_turn", ...NO_RUN });
  const bound = buildSummaryFixture({
    traceId: "t",
    sessionId: "s",
    reasonCode: "runtime_finished",
    runIdentity: { ...productRun(), prompt: "secret" },
  });
  const parsed = parseTurnExecutionSummary(bound).runIdentity;
  assert.equal(parsed.kind, "product_run");
  assert.equal("prompt" in parsed, false);
  const { run_identity: _dropped, ...withoutIdentity } = payload;
  assert.equal(parseTurnExecutionSummary(withoutIdentity).runIdentity.kind, "unresolved");
});

const BACKEND = new URL("../../../../backend/app/", import.meta.url);

function backendTuple(relativePath, name) {
  const source = readFileSync(new URL(relativePath, BACKEND), "utf8").replace(/\r\n/g, "\n");
  const start = source.indexOf(`${name}`);
  assert.notEqual(start, -1, `missing backend tuple: ${name}`);
  const body = source.slice(source.indexOf("(", start), source.indexOf("\n)", start) + 2);
  const constants = Object.fromEntries(
    [...source.matchAll(/^(RUN_STATE_[A-Z_]+) = "([a-z_]+)"$/gm)].map((match) => [match[1], match[2]]),
  );
  return [...body.matchAll(/"([a-z_]+)"|(RUN_STATE_[A-Z_]+)/g)].map((match) => match[1] ?? constants[match[2]]);
}

test("frontend closed sets equal the backend vocabularies", () => {
  const kinds = readFileSync(new URL("services/session/turn_run_identity.py", BACKEND), "utf8");
  assert.match(kinds, /^RUN_IDENTITY_KINDS = \("product_run", "unscoped_turn", "compat_turn", "unresolved"\)$/m);
  assert.deepEqual([...TURN_RUN_IDENTITY_KINDS], ["product_run", "unscoped_turn", "compat_turn", "unresolved"]);

  const reserved = ["verifying"];
  const states = backendTuple("models/runtime/product_run.py", "RUN_STATES: tuple[str, ...] = (");
  assert.equal(states.length, 14);
  assert.deepEqual(
    [...TURN_RUN_STATES],
    [...states.filter((state) => !reserved.includes(state)), "unknown"],
  );
  const reasons = backendTuple("models/runtime/product_run.py", "RUN_END_REASONS: tuple[str, ...] = (");
  assert.equal(reasons.length, 22);
  assert.deepEqual([...TURN_RUN_END_REASONS], [...reasons, "unknown"]);
});
