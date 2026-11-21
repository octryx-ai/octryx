// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Guards the frontend enums and the e2e fixtures against drift from the
// backend `turn_execution_summary.v1` builder. The backend source is read
// (never imported or executed) and its literal tables are compared.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  TURN_EXECUTION_STATES,
  TURN_NEXT_ACTION_KINDS,
} from "../../src/chat/run/turnExecutionSummary.types.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import {
  presentNextAction,
  presentTurnExecutionState,
} from "../../src/chat/run/turnExecutionSummaryPresentation.ts";
import {
  BACKEND_NEXT_ACTIONS,
  BACKEND_REASONS,
  BACKEND_STATE_BY_REASON,
  BACKEND_SUMMARY_STATES,
  GATE_SOURCE_PROFILE,
  PROFILE_DECISION_SOURCES,
  buildSummaryFixture,
  profileSection,
} from "../e2e/turnExecutionSummaryFixtures.mjs";

const BACKEND_SERVICES = new URL("../../../../backend/app/services/", import.meta.url);

function backendSource(relativePath) {
  return readFileSync(new URL(relativePath, BACKEND_SERVICES), "utf8").replace(/\r\n/g, "\n");
}

const SUMMARY_SOURCE = backendSource("session/turn_execution_summary.py");

function block(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.notEqual(start, -1, `missing backend marker: ${startMarker}`);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1, `missing end of backend block: ${startMarker}`);
  return source.slice(start, end);
}

// Module-level constants such as `_CONTACT_ADMIN = "..."` or
// `_NO_ACTION: tuple[...] = ("none", None)` referenced by the tables.
function backendConstants() {
  const constants = {};
  for (const match of SUMMARY_SOURCE.matchAll(/^(_[A-Z_]+)(?::[^=\n]+)? = (.+)$/gm)) {
    constants[match[1]] = match[2].trim();
  }
  return constants;
}

function pyValue(token, constants) {
  const value = token.trim();
  if (value === "None") {
    return null;
  }
  if (value.startsWith('"')) {
    return JSON.parse(value);
  }
  if (value.startsWith("(")) {
    return pyTuple(value, constants);
  }
  assert.ok(value in constants, `unresolved backend constant: ${value}`);
  return pyValue(constants[value], constants);
}

function pyTuple(value, constants) {
  const inner = value.replace(/^\(\s*/, "").replace(/,?\s*\)$/, "");
  const parts = [...inner.matchAll(/"[^"]*"|None|_[A-Z_]+/g)].map((m) => m[0]);
  return parts.map((part) => pyValue(part, constants));
}

function backendPairs(startMarker) {
  const constants = backendConstants();
  const body = block(SUMMARY_SOURCE, startMarker, "\n}");
  const entries = [
    ...body.matchAll(/^\s{4}"([a-z_]+)":\s*(\((?:[^()"]|"[^"]*")*\)|_[A-Z_]+),$/gm),
  ];
  return Object.fromEntries(entries.map((m) => [m[1], pyValue(m[2], constants)]));
}

function backendSummaryStates() {
  const body = block(SUMMARY_SOURCE, "SUMMARY_STATES = (", "\n)");
  return [...body.matchAll(/^\s*"([a-z_]+)",$/gm)].map((match) => match[1]);
}

function backendStateByReason() {
  const body = block(SUMMARY_SOURCE, "_STATE_BY_REASON: dict[str, str] = {", "\n}");
  const entries = [...body.matchAll(/^\s*"([a-z_]+)":\s*"([a-z_]+)",$/gm)];
  return Object.fromEntries(entries.map((m) => [m[1], m[2]]));
}

test("frontend states equal the backend closed state list", () => {
  const backend = backendSummaryStates();
  assert.equal(backend.length, 13); // + "started": a phased workflow's run started from the chat
  assert.deepEqual([...TURN_EXECUTION_STATES], backend);
  assert.deepEqual(BACKEND_SUMMARY_STATES, backend);
});

test("frontend action kinds align with every backend-emitted action kind", () => {
  const backend = backendPairs("_NEXT_ACTIONS: dict[str, tuple[str, str | None]] = {");
  assert.equal(Object.keys(backend).length, 29); // +2 answer-evidence stops, +3 reply-contract stops, +2 phased start
  const emittedKinds = [...new Set(Object.values(backend).map(([kind]) => kind))].sort();
  assert.deepEqual([...TURN_NEXT_ACTION_KINDS].sort(), emittedKinds);
  for (const [kind, label] of Object.values(backend)) {
    const presented = presentNextAction({ kind, label: null });
    assert.notEqual(presented, "Unrecognized next action", kind);
    // A null label in the table is rendered from the prompt catalog at build time.
    if (label !== null) {
      assert.equal(presentNextAction({ kind, label }), kind === "none" ? null : label);
    }
  }
});

test("fixture reason, action and state tables equal the backend tables", () => {
  const reasons = backendPairs("_REASONS: dict[str, tuple[str, str]] = {");
  assert.equal(Object.keys(reasons).length, 29); // +2 answer-evidence stops, +3 reply-contract stops, +2 phased start
  assert.deepEqual(BACKEND_REASONS, reasons);
  assert.deepEqual(
    BACKEND_NEXT_ACTIONS,
    backendPairs("_NEXT_ACTIONS: dict[str, tuple[str, str | None]] = {"),
  );
  assert.deepEqual(BACKEND_STATE_BY_REASON, backendStateByReason());
});

test("fixture profile section has the backend key shape with a nested gate", () => {
  const body = block(SUMMARY_SOURCE, "def _profile_section(", "\ndef ");
  const backendKeys = [...body.matchAll(/"([a-z_]+)":/g)].map((match) => match[1]);
  const profile = profileSection({
    profileId: "direct_chat_safe",
    status: "allowed",
    decisionSource: PROFILE_DECISION_SOURCES.directChat,
  });
  const fixtureKeys = Object.entries(profile).flatMap(([key, value]) =>
    key === "gate" ? [key, ...Object.keys(value)] : [key],
  );
  assert.deepEqual(fixtureKeys, backendKeys);
  assert.deepEqual(profile.gate, {
    outcome: "allowed",
    status: "allowed",
    decision_source: "execution_profile",
  });
});

test("fixture gate and profile decision sources are real backend values", () => {
  const gateSource = backendSource("session/execution_gate.py");
  assert.match(gateSource, new RegExp(`^GATE_SOURCE_PROFILE = "${GATE_SOURCE_PROFILE}"$`, "m"));
  const producers =
    backendSource("execution_profile_service.py") + backendSource("execution_profile_requirements.py");
  for (const source of Object.values(PROFILE_DECISION_SOURCES)) {
    assert.ok(producers.includes(`"${source}"`), source);
  }
});

function profileForReason(reasonCode) {
  const source = BACKEND_REASONS[reasonCode][0];
  if (source === "trace") {
    return null;
  }
  if (reasonCode === "gate_needs_confirmation") {
    // Workflow proposal gate: an allowed profile, blocked by the proposal.
    return {
      ...profileSection({ profileId: "direct_chat_safe", status: "allowed", decisionSource: null }),
      gate: { outcome: "blocked", status: "needs_confirmation", decision_source: "workflow_proposal" },
    };
  }
  if (reasonCode === "gate_blocked_unknown") {
    // Missing-profile block: unknown profile, gate status `missing`.
    return {
      ...profileSection({ profileId: null, status: "unknown", decisionSource: null }),
      gate: { outcome: "blocked", status: "missing", decision_source: "missing_profile" },
    };
  }
  const status = source === "execution_gate" ? reasonCode.slice("gate_".length) : "allowed";
  return profileSection({
    profileId: `${status}:${PROFILE_DECISION_SOURCES.workflowRequirements}`,
    status,
    decisionSource: PROFILE_DECISION_SOURCES.workflowRequirements,
  });
}

test("every backend reason builds a fixture the client parses and presents", () => {
  const gateSources = backendSource("session/execution_gate.py");
  for (const reasonCode of Object.keys(BACKEND_REASONS)) {
    const profile = profileForReason(reasonCode);
    const payload = buildSummaryFixture({
      traceId: "trace-1",
      sessionId: "session-1",
      reasonCode,
      profile,
      model: { provider: "bedrock", model: "nova" },
    });
    const parsed = parseTurnExecutionSummary(payload);
    assert.equal(parsed.state, BACKEND_STATE_BY_REASON[reasonCode], reasonCode);
    assert.notEqual(presentTurnExecutionState(parsed.state).label, "Unrecognized status");
    assert.equal(parsed.stateReason.code, reasonCode);
    assert.equal(parsed.stateReason.source, BACKEND_REASONS[reasonCode][0]);
    if (profile === null) {
      assert.equal(parsed.executionProfile, null, reasonCode);
      continue;
    }
    const gate = parsed.executionProfile.gate;
    assert.ok(gateSources.includes(`"${gate.decisionSource}"`), gate.decisionSource);
    const blocked = BACKEND_REASONS[reasonCode][0] === "execution_gate";
    assert.equal(gate.outcome, blocked ? "blocked" : "allowed", reasonCode);
    assert.equal(parsed.modelLabel, blocked ? null : "bedrock / nova", reasonCode);
  }
});
