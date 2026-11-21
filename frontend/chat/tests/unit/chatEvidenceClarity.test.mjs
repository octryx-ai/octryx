// Chat evidence clarity regression: a follow-up answer
// showed "Evidence: Unsourced" beside "Sources · 1" and runtime jargon, and repository source rows
// wrapped long paths inside the file extension. Semantics stay; the wording and labels are clearer.
// `unsourced` means the turn's tool results carry no openable source (answer_evidence/check.py), so
// the wording claims neither that nothing was read nor where the answer's links came from.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { presentAnswerEvidence } from "../../src/chat/run/turnAnswerEvidence.ts";
import { turnStateReasonText } from "../../src/chat/run/turnStateReason.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const loader = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* TS uses shared loader. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { TurnExecutionStatusCard } = await import("../../src/chat/run/TurnExecutionStatusCard.tsx");
const { AnswerSourcesButton } = await import("../../src/chat/evidence/AnswerSourcesButton.tsx");
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const ORIGIN = "http://localhost:8090";
const flatten = (node) => (node === null || node === undefined ? "" : typeof node === "string" ? node
  : Array.isArray(node) ? node.map(flatten).join("") : flatten(node.children));

test("the unsourced marker is scoped to this turn and never turns a link into verification", () => {
  const unsourced = presentAnswerEvidence({ state: "unsourced", citedCount: 0, uncitedCount: 1 });
  assert.equal(unsourced.label, "No source evidence this turn");
  assert.equal(unsourced.tone, "neutral");
  assert.equal(unsourced.explain, true);
  assert.equal(
    unsourced.description,
    "No supporting source is recorded for this turn. Sources lists links cited in the answer; they have not been checked against evidence from this turn.",
  );
  // No claim that nothing was read, no tool counts, no history provenance, no verification.
  assert.doesNotMatch(unsourced.description, /was read|no source read|earlier|previous|history|tool|verified/i);
  // Other states keep their meaning, tone and wording; no visible explanation is added.
  const passed = presentAnswerEvidence({ state: "passed", citedCount: 2, uncitedCount: 0 });
  assert.deepEqual([passed.label, passed.tone, passed.explain], ["Sources cited", "success", undefined]);
  const refused = presentAnswerEvidence({ state: "refused", citedCount: 0, uncitedCount: 2 });
  assert.deepEqual([refused.label, refused.tone], ["Answer withheld", "attention"]);
  assert.equal(presentAnswerEvidence({ state: "reminded", citedCount: 0, uncitedCount: 1 }), null);
});

test("only the known finished_unverified / runtime_finished reason is translated", () => {
  const backend = "The agent turn finished without an accepted Verification Contract.";
  assert.equal(
    turnStateReasonText("finished_unverified", "runtime_finished", backend, "fallback"),
    "The reply is ready. It has not passed an automated verification step.",
  );
  assert.equal(turnStateReasonText("finished_unverified", "other_reason", "Backend detail.", "fallback"), "Backend detail.");
  assert.equal(turnStateReasonText("completed", "runtime_finished", "Backend detail.", "fallback"), "Backend detail.");
  assert.equal(turnStateReasonText({ unrecognized: "x" }, "runtime_finished", null, "State description."), "State description.");
  assert.equal(turnStateReasonText("finished_unverified", "constructor", null, "State description."), "State description.");
});

function cardFor(answerEvidence) {
  const summary = parseTurnExecutionSummary({ ...buildSummaryFixture({ traceId: "t1", sessionId: "s1", reasonCode: "runtime_finished" }), answer_evidence: answerEvidence });
  let view;
  act(() => { view = TestRenderer.create(createElement(TurnExecutionStatusCard, { load: { status: "ready", summary }, onRetry() {} })); });
  return view;
}

test("the status card explains an unsourced turn in visible text and drops the contract jargon", () => {
  const view = cardFor({ evidence_guard: "unsourced", cited_count: 0, uncited_count: 1 });
  const all = flatten(view.toJSON());
  assert.match(all, /Evidence: No source evidence this turn/);
  assert.match(all, /The reply is ready\. It has not passed an automated verification step\./);
  assert.doesNotMatch(all, /Verification Contract|Unsourced|complete|Check it yourself/);
  const explanation = view.root.findAll((node) => node.props?.["data-evidence-explanation"] !== undefined && typeof node.type === "string");
  assert.equal(explanation.length, 1, "the explanation is visible text, not only a tooltip");
  assert.match(flatten(explanation[0].children), /^No supporting source is recorded for this turn\./);
  act(() => view.unmount());
  const passed = cardFor({ evidence_guard: "passed", cited_count: 2, uncited_count: 0 });
  assert.match(flatten(passed.toJSON()), /Evidence: Sources cited/);
  assert.equal(passed.root.findAll((node) => node.props?.["data-evidence-explanation"] !== undefined && typeof node.type === "string").length, 0);
  act(() => passed.unmount());
});

test("cited sources: web titles stay unchanged, unsafe links stay excluded", () => {
  const previousObserver = globalThis.MutationObserver;
  const previousWindow = globalThis.window;
  globalThis.window = { location: { origin: ORIGIN } };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  const link = (href, label) => ({ getAttribute: () => href, textContent: label, closest: () => ({ textContent: "Claim" }) });
  const links = [
    link("https://docs.spring.io/spring-boot/reference/web/servlet.html", "Spring Boot / Servlet Web Applications"),
    link("javascript:alert(1)", "bad"),
  ];
  const article = { querySelector: () => ({}), querySelectorAll: () => links };
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(AnswerSourcesButton, { contentKey: "answer" }), {
      createNodeMock: (element) => element.type === "button" ? { closest: () => article } : {},
    }); });
    const anchors = view.root.findAllByType("a");
    assert.deepEqual(anchors.map((anchor) => flatten(anchor.children)), ["Spring Boot / Servlet Web Applications"]);
    assert.match(flatten(view.toJSON()), /1 unsafe or unsupported links are not listed/);
  } finally { act(() => view?.unmount()); globalThis.MutationObserver = previousObserver; globalThis.window = previousWindow; }
});
