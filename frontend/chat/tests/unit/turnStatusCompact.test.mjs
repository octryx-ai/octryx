// (screenshot 39): a one-word "Bereit." answer sat under a status card with two explanatory
// paragraphs. Only the exact benign terminal status (finished_unverified / runtime_finished, nothing
// to do, no refused or reminded evidence) folds its explanation into a native disclosure. The state
// and the evidence label stay visible. Every
// other combination keeps the full card. Component tests only; the rendered UI is judged by the root.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { isCompactTurnStatus } from "../../src/chat/run/turnStatusCompact.ts";
import { BACKEND_STATE_BY_REASON, buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

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
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const flatten = (node) => (node === null || node === undefined ? "" : typeof node === "string" ? node
  : Array.isArray(node) ? node.map(flatten).join("") : flatten(node.children));

const UNSOURCED = { evidence_guard: "unsourced", cited_count: 0, uncited_count: 1 };

function raw({ reasonCode = "runtime_finished", answerEvidence = UNSOURCED, ...overrides } = {}) {
  return { ...buildSummaryFixture({ traceId: "t1", sessionId: "s1", reasonCode, ...overrides }), answer_evidence: answerEvidence };
}
const summary = (options) => parseTurnExecutionSummary(raw(options));
const withRaw = (patch) => parseTurnExecutionSummary({ ...raw(), ...patch });

// --- the predicate --------------------------------------------------------------------

test("the exact benign terminal status is compact only with explicitly recognized evidence", () => {
  assert.equal(isCompactTurnStatus(summary()), true);
  assert.equal(isCompactTurnStatus(summary({ answerEvidence: { evidence_guard: "passed", cited_count: 2, uncited_count: 0 } })), true);
});

test("absent, unknown or malformed evidence parses to null and keeps the full card", () => {
  const absent = raw();
  delete absent.answer_evidence;
  assert.equal(isCompactTurnStatus(parseTurnExecutionSummary(absent)), false, "no evidence recorded");
  for (const answerEvidence of [
    null,
    { evidence_guard: "verified_by_magic", cited_count: 3, uncited_count: 0 },
    { evidence_guard: "PASSED" },
    { cited_count: 1 },
    "passed",
    ["passed"],
  ]) {
    const parsed = summary({ answerEvidence });
    const label = String(JSON.stringify(answerEvidence));
    assert.equal(parsed.answerEvidence, null, label);
    assert.equal(isCompactTurnStatus(parsed), false, label);
  }
  const view = render(summary({ answerEvidence: { evidence_guard: "verified_by_magic" } }));
  assert.equal(disclosures(view).length, 0, "an unknown evidence value renders the full card");
  assert.ok(view.root.findAll((node) => node.type === "p" && node.props.className === "turn-exec-card__reason").length >= 1);
  act(() => view.unmount());
});

test("every other state or reason stays expanded", () => {
  for (const reasonCode of Object.keys(BACKEND_STATE_BY_REASON).filter((code) => code !== "runtime_finished")) {
    assert.equal(isCompactTurnStatus(summary({ reasonCode })), false, reasonCode);
  }
  assert.equal(isCompactTurnStatus(withRaw({ state: "finished_later" })), false, "unfamiliar state");
  assert.equal(isCompactTurnStatus(withRaw({ state_reason: { code: "runtime_finished_v2", source: "runtime", text: "x" } })), false, "nonstandard reason");
  assert.equal(isCompactTurnStatus(withRaw({ state_reason: { code: null, source: null, text: null } })), false, "missing reason");
});

test("action, decision, proposal, approval and evidence concerns stay expanded", () => {
  const base = raw();
  const cases = {
    "next action": { next_action: { kind: "retry", label: null } },
    "unfamiliar next action": { next_action: { kind: "phone_home", label: null } },
    "decision request": { decision_request: { decision_key: "capability_escalation", options: [{ value: "allow_changes", label: "Allow changes" }] } },
    "workflow proposal": { workflow_proposal: { workflow_key: "release-notes", title: "Release notes", status: "proposed" } },
    approvals: { approvals: [{ id: "a1", tool_name: "create_branch", status: "approved" }] },
    "refused evidence": { answer_evidence: { evidence_guard: "refused", cited_count: 0, uncited_count: 2 } },
    "reminded evidence": { answer_evidence: { evidence_guard: "reminded", cited_count: 0, uncited_count: 1 } },
  };
  for (const [name, patch] of Object.entries(cases)) {
    const parsed = parseTurnExecutionSummary({ ...base, ...patch });
    assert.ok(parsed, name);
    if (name === "decision request") assert.ok(parsed.decisionRequest, "the fixture parses as a real decision request");
    if (name === "workflow proposal") assert.ok(parsed.workflowProposal, "the fixture parses as a real proposal");
    if (name === "approvals") assert.equal(parsed.approvals.length, 1, "the fixture parses as a real approval");
    assert.equal(isCompactTurnStatus(parsed), false, name);
  }
});

// --- the card -------------------------------------------------------------------------

function render(parsed, props = {}) {
  let view;
  act(() => { view = TestRenderer.create(createElement(TurnExecutionStatusCard, { load: { status: "ready", summary: parsed }, onRetry() {}, ...props })); });
  return view;
}
const disclosures = (view) => view.root.findAll((node) => node.type === "details");
const card = (view) => view.root.find((node) => node.type === "section");

test("the compact card keeps the status row visible and folds both paragraphs into a native disclosure", () => {
  let opened = 0;
  const view = render(summary(), { onOpenDetails: () => { opened += 1; } });
  assert.match(card(view).props.className, /turn-exec-card--compact/);
  const [details] = disclosures(view);
  assert.ok(details, "a native <details> holds the explanation");
  assert.notEqual(details.props.open, true, "closed by default");
  const [label] = details.findAll((node) => node.type === "summary");
  assert.equal(flatten(label.children), "About this status");
  const inside = flatten(details.children);
  assert.match(inside, /The reply is ready\. It has not passed an automated verification step\./);
  assert.match(inside, /No supporting source is recorded for this turn\./, "the evidence explanation stays available");
  // Outside the disclosure: the honest status cue stays visible.
  const row = view.root.find((node) => node.props?.className === "turn-exec-card__row");
  assert.match(flatten(row.children), /Finished, unverified.*Evidence: No source evidence this turn/);
  // Details stays the same callback.
  const detailsButton = view.root.findByProps({ "aria-label": "Open execution details" });
  act(() => detailsButton.props.onClick());
  assert.equal(opened, 1);
  act(() => view.unmount());
});

test("without a Details callback the explanation is still reachable through the disclosure", () => {
  const view = render(summary());
  assert.equal(view.root.findAll((node) => node.props?.["aria-label"] === "Open execution details").length, 0);
  const [details] = disclosures(view);
  assert.match(flatten(details.children), /It has not passed an automated verification step/);
  act(() => view.unmount());
});

test("non-benign cards keep every explanation and action expanded, with no disclosure", () => {
  const refused = render(summary({ answerEvidence: { evidence_guard: "refused", cited_count: 0, uncited_count: 2 } }));
  assert.equal(disclosures(refused).length, 0);
  assert.match(flatten(refused.toJSON()), /Evidence: Answer withheld/);
  assert.doesNotMatch(card(refused).props.className, /--compact/);
  act(() => refused.unmount());

  const blocked = render(summary({ reasonCode: "gate_needs_configuration" }));
  assert.equal(disclosures(blocked).length, 0);
  const text = flatten(blocked.toJSON());
  assert.match(text, /Needs configuration/);
  assert.match(text, /Next: /, "the next action stays visible");
  const paragraphs = blocked.root.findAll((node) => node.type === "p" && node.props.className === "turn-exec-card__reason");
  assert.ok(paragraphs.length >= 1, "the reason paragraph stays visible");
  act(() => blocked.unmount());
});

// Regression: the persisted summary of the one-word "Bereit." reply
// carried this exact record, not null, so the ordinary case stayed expanded.
const LIVE_NO_WORKFLOW_PROPOSAL = {
  status: "none", reason_code: "user_selected_no_workflow", proposal_id: null, workflow_key: null,
  workflow_title: null, confidence: null, change_capable: null,
};

test("the live plain-chat summary with an inert 'none' proposal is compact through parser and card", () => {
  const live = parseTurnExecutionSummary({ ...raw(), workflow_proposal: LIVE_NO_WORKFLOW_PROPOSAL });
  assert.ok(live.workflowProposal, "the record parses as a proposal, not as null");
  assert.equal(live.workflowProposal.status, "none");
  assert.equal(isCompactTurnStatus(live), true);
  const view = render(live);
  assert.equal(disclosures(view).length, 1);
  assert.match(flatten(view.root.find((node) => node.props?.className === "turn-exec-card__row").children),
    /Finished, unverified.*Evidence: No source evidence this turn/);
  act(() => view.unmount());
  for (const reason_code of ["no_match", "no_published_definitions"]) {
    assert.equal(isCompactTurnStatus(parseTurnExecutionSummary({ ...raw(), workflow_proposal: { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code } })), true, reason_code);
  }
});

test("any other or inconsistent proposal keeps the full card", () => {
  const cases = {
    "needs confirmation": { status: "needs_confirmation", reason_code: "workflow_run_required", proposal_id: "p1", workflow_key: "release-notes", workflow_title: "Release notes", confidence: "high", change_capable: true },
    offered: { status: "offered", reason_code: "offered_not_requested", proposal_id: "p1", workflow_key: "kb", workflow_title: "KB", confidence: "high", change_capable: false },
    disabled: { ...LIVE_NO_WORKFLOW_PROPOSAL, status: "disabled", reason_code: "policy_disabled" },
    "unfamiliar status": { ...LIVE_NO_WORKFLOW_PROPOSAL, status: "pending_review" },
    "proposal call timed out": { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code: "timeout" },
    "model unavailable": { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code: "model_unavailable" },
    "scope changed": { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code: "proposal_scope_changed" },
    "unfamiliar reason": { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code: "something_new" },
    "missing reason": { ...LIVE_NO_WORKFLOW_PROPOSAL, reason_code: null },
    "none with an identity": { ...LIVE_NO_WORKFLOW_PROPOSAL, proposal_id: "p1" },
    "none with a key": { ...LIVE_NO_WORKFLOW_PROPOSAL, workflow_key: "release-notes" },
    "none with a title": { ...LIVE_NO_WORKFLOW_PROPOSAL, workflow_title: "Release notes" },
    "none with a confidence": { ...LIVE_NO_WORKFLOW_PROPOSAL, confidence: "low" },
    "none with a change request": { ...LIVE_NO_WORKFLOW_PROPOSAL, change_capable: true },
  };
  for (const [name, workflow_proposal] of Object.entries(cases)) {
    const parsed = parseTurnExecutionSummary({ ...raw(), workflow_proposal });
    assert.ok(parsed.workflowProposal, `${name} parses as a proposal`);
    assert.equal(isCompactTurnStatus(parsed), false, name);
  }
});

