// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Answer evidence section of `turn_execution_summary.v1` (evidence enforcement E1):
// the typed parse, the closed presentation with `unsourced` as the explicit marker,
// and a drift guard against the backend closed set (backend source is read, never executed).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  TURN_ANSWER_EVIDENCE_STATES,
  parseTurnAnswerEvidence,
  presentAnswerEvidence,
} from "../../src/chat/run/turnAnswerEvidence.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const RECORD_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/answer_evidence/record.py", import.meta.url),
  "utf8",
);

test("the closed states match the backend record", () => {
  const backend = [...RECORD_SOURCE.matchAll(/^GUARD_[A-Z]+ = "([a-z_]+)"$/gm)].map((match) => match[1]);
  assert.deepEqual([...backend].sort(), [...TURN_ANSWER_EVIDENCE_STATES].sort());
});

test("a record parses into closed values and bounded counts", () => {
  assert.deepEqual(
    parseTurnAnswerEvidence({ evidence_guard: "passed", cited_count: 3, uncited_count: 0, extra: "x" }),
    { state: "passed", citedCount: 3, uncitedCount: 0 },
  );
  assert.deepEqual(parseTurnAnswerEvidence({ evidence_guard: "refused", cited_count: "3" }), {
    state: "refused",
    citedCount: null,
    uncitedCount: null,
  });
  assert.equal(parseTurnAnswerEvidence({ evidence_guard: "maybe" }), null);
  assert.equal(parseTurnAnswerEvidence(null), null);
});

test("unsourced is the explicit marker and only passed has the success tone", () => {
  // Turn-scoped wording: no openable source evidence this turn, not that links are absent.
  assert.equal(presentAnswerEvidence({ state: "unsourced", citedCount: 0, uncitedCount: 1 }).label, "No source evidence this turn");
  // `marked` (backend): delivered in full with its shortfalls marked; it reads as attention, never as success.
  const marked = presentAnswerEvidence(parseTurnAnswerEvidence({ evidence_guard: "marked", cited_count: 2, uncited_count: 1 }));
  assert.deepEqual([marked.tone, marked.label, marked.explain], ["attention", "Some claims unsourced", true]);
  assert.equal(presentAnswerEvidence({ state: "passed", citedCount: 2, uncitedCount: 0 }).tone, "success");
  assert.equal(presentAnswerEvidence({ state: "refused", citedCount: 0, uncitedCount: 2 }).tone, "attention");
  assert.equal(presentAnswerEvidence({ state: "reminded", citedCount: 0, uncitedCount: 2 }), null);
  assert.equal(presentAnswerEvidence(null), null);
});

test("the summary parse carries the section", () => {
  const fixture = buildSummaryFixture({ traceId: "t1", sessionId: "s1", reasonCode: "runtime_finished" });
  const withRecord = { ...fixture, answer_evidence: { evidence_guard: "unsourced", cited_count: 0, uncited_count: 1 } };
  assert.equal(parseTurnExecutionSummary(withRecord).answerEvidence.state, "unsourced");
  assert.equal(parseTurnExecutionSummary(fixture).answerEvidence, null);
});
