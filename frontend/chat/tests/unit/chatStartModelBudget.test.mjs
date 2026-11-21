// The chat start card's Model and Cost budget (`model` next to `run_on`; the limits PUT is a patch since
// ) and Workspace settings › Knowledge › "Documentation target" (project config `feature_documentation`).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  answerModel,
  runOnTarget,
  startBudget,
  startBudgetError,
  startModelError,
  storedCost,
} from "../../src/chat/run/startCardChoices.ts";
import { proposalAnswerBody } from "../../src/chat/run/workflowProposalAnswer.ts";
import { CODEX_SEAT_MODELS, modelOptions, modelSource } from "../../src/chat/workflowRun/runModelModel.ts";
import {
  confluenceSources,
  docTargetBody,
  docTargetProblems,
  docTargetSaveErrors,
  docTargetWarnings,
  DOC_TARGET_INTRO,
  offeredSpaces,
  PARENT_MISSING,
  PARENT_MISSING_AUTO,
  readDocTarget,
} from "../../src/admin/components/workspaceSettings/documentationTargetModel.ts";

const SEAT_KEY = "device:d1:seat:/Users/me/coffee";
const GOVERNED_KEY = "device:d1:governed:C:\\work\\coffee";

test("a Run on key names its target: a device key keeps a folder with ':' whole, other keys are their kind", () => {
  assert.deepEqual(runOnTarget(SEAT_KEY), { kind: "device", device_id: "d1", profile: "seat", folder: "/Users/me/coffee" });
  assert.deepEqual(runOnTarget(GOVERNED_KEY), { kind: "device", device_id: "d1", profile: "governed", folder: "C:\\work\\coffee" });
  assert.deepEqual(runOnTarget("server"), { kind: "server" });
  assert.equal(runOnTarget("device:d1:seat:"), null);
  assert.equal(runOnTarget("elsewhere"), null);
});

test("model options follow the chosen location's profile and the engine", () => {
  const rows = { models: [{ id: "claude-sonnet-5-5", label: "Sonnet 5.5" }], reason: null };
  const seat = modelSource("claude_code", runOnTarget(SEAT_KEY));
  assert.deepEqual(seat, { kind: "server", profile: "seat", deviceId: "d1" });
  assert.deepEqual(modelOptions(seat, rows).map((option) => option.value), ["", "claude-sonnet-5-5"]);
  assert.deepEqual(modelSource("claude_code", runOnTarget(GOVERNED_KEY)), { kind: "server", profile: "governed", deviceId: "d1" });
  // Codex on the own subscription: the server has no list, the GPT-6 models are offered.
  const codex = modelSource("codex", runOnTarget(SEAT_KEY));
  assert.deepEqual(modelOptions(codex, null).map((option) => option.value), ["", ...CODEX_SEAT_MODELS]);
  // Server / Automatic: only Automatic, the select is disabled with its sentence.
  for (const key of ["server", "auto", "terminal"]) assert.equal(modelSource("claude_code", runOnTarget(key)).kind, "none");
});

test("the answer carries the model only with Start on a device location", () => {
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", runOn: SEAT_KEY, model: "gpt-6.1-sol" }),
    { proposal_id: "p1", decision: "apply", run_on: SEAT_KEY, model: "gpt-6.1-sol" });
  // Automatic, the Server or no Run on: no model (the server would refuse it with 422).
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", runOn: SEAT_KEY, model: "" }),
    { proposal_id: "p1", decision: "apply", run_on: SEAT_KEY });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", runOn: "server", model: "x" }),
    { proposal_id: "p1", decision: "apply", run_on: "server" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", model: "x" }), { proposal_id: "p1", decision: "apply" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "skip", runOn: SEAT_KEY, model: "x" }), { proposal_id: "p1", decision: "skip" });
  assert.equal(answerModel(SEAT_KEY, " claude-sonnet-5-5 "), "claude-sonnet-5-5");
});

test("the model refusals land at the Model field; other refusals do not", () => {
  assert.match(startModelError("This model is not allowed here (not a seat model)."), /not allowed on this device and route \(not a seat model\)/);
  assert.match(startModelError("Choose one of your devices under Run on to pick a model."), /Pick one of your devices/);
  assert.equal(startModelError("Choose the repository the run works in."), null);
});

test("the cost budget rides on the start answer, for a new Epic as for an existing item", () => {
  assert.deepEqual(startBudget(" 15 "), { budget: { cost_usd: 15 } });
  assert.deepEqual(startBudget(""), { budget: null });
  assert.ok("error" in startBudget("-3"));
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", runOn: "auto", budget: { cost_usd: 15 } }),
    { proposal_id: "p1", decision: "apply", run_on: "auto", budget: { cost_usd: 15 } });
  // Only Start carries it; an empty field sends none (the item keeps its stored budget).
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "skip", budget: { cost_usd: 15 } }), { proposal_id: "p1", decision: "skip" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p1", decision: "apply", budget: null }), { proposal_id: "p1", decision: "apply" });
  // The server's 422 lands at the cost field; other refusals do not.
  assert.match(startBudgetError("Invalid budget: cost_usd must be a positive number"), /did not accept this budget \(cost_usd must be a positive number\)/);
  assert.equal(startBudgetError("Choose the repository the run works in."), null);
  assert.equal(storedCost({ run_limits: { loop_limit: 3, budget: { cost_usd: 12.5, tokens: 9 } } }), 12.5);
  assert.equal(storedCost({ run_limits: {} }), null);
});

test("the documentation target is read from feature_documentation and written as that one key, other sub-keys untouched", () => {
  const config = { config: { tts: { voice: "a" }, feature_documentation: {
    confluence_space_key: "eng", parent_page_id: 42, knowledge_connector_key: "conf-eng", audience_proof: { x: 1 } } } };
  const target = readDocTarget(config);
  assert.deepEqual(target, { spaceKey: "ENG", parentPageId: "42", connectorKey: "conf-eng", autoPublish: false });
  assert.deepEqual(docTargetBody({ ...target, autoPublish: true, spaceKey: " eng " }), { feature_documentation: {
    confluence_space_key: "ENG", parent_page_id: "42", knowledge_connector_key: "conf-eng", auto_publish: true } });
  // Cleared fields are sent as "" (the server reads them as not set); no other top-level key is in the body.
  assert.deepEqual(Object.keys(docTargetBody({ spaceKey: "", parentPageId: "", connectorKey: "", autoPublish: false })), ["feature_documentation"]);
  assert.equal(readDocTarget({ config: { feature_documentation: { auto_publish: "yes" } } }).autoPublish, false);
});

test("the documentation target is checked before it is sent", () => {
  const ok = { spaceKey: "ENG", parentPageId: "123456", connectorKey: "", autoPublish: true };
  assert.deepEqual(docTargetProblems(ok), {});
  assert.deepEqual(docTargetProblems({ spaceKey: "", parentPageId: "", connectorKey: "", autoPublish: false }), {});
  assert.ok(docTargetProblems({ ...ok, spaceKey: "EN G" }).spaceKey);
  assert.ok(docTargetProblems({ ...ok, parentPageId: "pages/12" }).parentPageId);
  // A parent, a source or unattended publishing without a space would publish nowhere.
  assert.match(docTargetProblems({ ...ok, spaceKey: "" }).spaceKey, /Name the space first/);
});

test("the parent page is required (skips with no_parent_page): a warning, louder when automatic publishing is on", () => {
  const draft = { spaceKey: "ENG", parentPageId: "", connectorKey: "", autoPublish: false };
  assert.equal(docTargetWarnings(draft).parentPageId, PARENT_MISSING);
  assert.equal(docTargetWarnings({ ...draft, autoPublish: true }).parentPageId, PARENT_MISSING_AUTO);
  assert.deepEqual(docTargetWarnings({ ...draft, parentPageId: "123", autoPublish: true }), {});
  assert.deepEqual(docTargetWarnings({ ...draft, spaceKey: "" }), {});
  // A warning, not a save blocker: the target can still be stored while the parent is looked up.
  assert.deepEqual(docTargetProblems({ ...draft, autoPublish: true }), {});
  assert.match(DOC_TARGET_INTRO, /never deletes, moves or writes to other spaces/);
});

test("refusals of the config PUT are words, at the field the server names", () => {
  assert.ok(docTargetSaveErrors(422, { detail: [{ loc: ["body", "feature_documentation", "auto_publish"], msg: "bool" }] }).autoPublish);
  assert.match(docTargetSaveErrors(403, { detail: "Admin access required" }).general, /only a platform admin/);
  assert.match(docTargetSaveErrors(422, { detail: "Connection fields belong elsewhere" }).general, /Connection fields belong elsewhere/);
  assert.match(docTargetSaveErrors(500, null).general, /did not answer/);
});

test("Confluence Knowledge sources and their spaces are offered for the target", () => {
  const sources = confluenceSources([
    { connector_key: "conf-eng", kind: "confluence", scope: { spaces: ["eng"], page_trees: [{ space_key: "DOC", root_page_id: "1" }] } },
    { connector_key: "jira-mm", kind: "jira", scope: { project_keys: ["CHEF"] } },
    { connector_key: "conf-ops", kind: "confluence", scope: { spaces: ["OPS"] } },
  ]);
  assert.deepEqual(sources, [{ key: "conf-eng", spaces: ["ENG", "DOC"] }, { key: "conf-ops", spaces: ["OPS"] }]);
  assert.deepEqual(offeredSpaces(sources, "conf-eng"), ["DOC", "ENG"]);
  assert.deepEqual(offeredSpaces(sources, ""), ["DOC", "ENG", "OPS"]);
});
