// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyBuilderContent.test.mjs
//
// Content policies in the guided builder: the Content and Outcome steps exist only for a content action,
// the outcome rules (no route for tool results, sticky only with a route, the approved-model exception only for
// Mask on Call a model), approved-model chips, the side badge and warning, and the server preview (no detection in
// the browser).

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  ROUTE_REFUSED, approvedAliases, categoriesOf, contentAction, effectBadge, normalizeContent, outcomeRefusal, previewMark,
  readContentPreview, readDetectorCatalog, routeTargetWarning, toggleDetector, withOutcome,
} from "../../src/admin/components/policyEngine/builderContentModel.ts";
import { blankModel, fromTemplate, readModel, startStep, stepDone, visibleSteps } from "../../src/admin/components/policyEngine/policyBuilderModel.ts";
import { readCatalog, readPickerEntities } from "../../src/admin/components/policyEngine/policyCatalogModel.ts";
import { CATALOG, act, byTestId, change, load, server, text, tick } from "./policyEngineHarness.mjs";

const catalog = readCatalog(CATALOG);
const template = (id) => catalog.templates.find((item) => item.id === id);
const DETECTORS = readDetectorCatalog({
  categories: [{ id: "pii", label: "Personal data" }, { id: "health", label: "Health data" }],
  detectors: [
    { id: "iban", category: "pii", label: "IBAN", method: "ISO 7064 mod-97", builtin: true },
    { id: "email", category: "pii", label: "Email address", method: "local@domain.tld", builtin: true },
    { id: "custom.ref", category: "confidential_identifier", label: "Reference", builtin: false },
  ],
});
const ALIASES = [
  { alias: "approved-model", dataPolicyClass: "restricted", approvedFor: ["pii", "health"] },
  { alias: "general-model", dataPolicyClass: "internal", approvedFor: [] },
];
const model = (patch = {}) => ({ ...blankModel(), id: "p", actions: ["call_model"], ...patch });
// A mask-and-route policy that still lacks its approved model (no shipped template has this shape).
const ROUTED_TEMPLATE = { id: "personal-data-approved-model", label: "Personal data only via the approved model", icon: "model",
  description: "", tags: [], section: "Sensitive data in requests and tool results",
  placeholders: [{ field: "outcome.reroute_to", label: "Approved model", hint: "Pick a model alias approved for personal data." }], model: {
  name: "Personal data only via the approved model", actions: ["call_model"],
  content: { detectors: ["email", "phone", "iban"], sticky: true, incomplete: true }, outcome: { kind: "mask_reroute", mask_style: "type_token" } } };
const ROUTED_CATALOG = { ...catalog, templates: [...catalog.templates, ROUTED_TEMPLATE] };
const ids = (steps) => steps.map((item) => item.id);

test("steps: Content and Outcome only for exactly one content action", () => {
  assert.deepEqual(ids(visibleSteps(model())), ["basics", "who", "what", "content", "where", "outcome", "exceptions", "check"]);
  assert.deepEqual(ids(visibleSteps(model({ actions: ["receive_tool_result"] }))).includes("outcome"), true);
  for (const actions of [["run_command"], ["call_model", "use_seat"], []]) {
    assert.deepEqual(ids(visibleSteps(model({ actions }))), ["basics", "who", "what", "where", "exceptions", "check"], actions.join());
  }
  assert.equal(contentAction(model({ actions: ["call_model", "receive_tool_result"] })), null);
  assert.equal(stepDone(model(), "content"), false);
  assert.equal(stepDone(withOutcome(model(), "reroute"), "outcome"), false, "a route needs its target");
});

test("outcome rules: route only for model requests, sticky follows the route, the exception only for Mask", () => {
  assert.equal(outcomeRefusal("reroute", "receive_tool_result"), ROUTE_REFUSED);
  assert.equal(outcomeRefusal("mask_reroute", "receive_tool_result"), ROUTE_REFUSED);
  assert.equal(outcomeRefusal("mask", "receive_tool_result"), "");
  assert.equal(outcomeRefusal("reroute", "call_model"), "");
  const routed = withOutcome(model(), "mask_reroute");
  assert.deepEqual([routed.content.sticky, routed.outcome.mask_style], [true, "type_token"]);
  const masked = withOutcome({ ...routed, outcome: { ...routed.outcome, reroute_to: "approved-model" } }, "mask");
  assert.deepEqual([masked.content.sticky, masked.outcome.reroute_to], [false, ""]);
  const excepted = { ...masked, outcome: { ...masked.outcome, approved_except: true } };
  assert.equal(withOutcome(excepted, "block").outcome.approved_except, false);
  assert.equal(withOutcome(excepted, "mask").outcome.approved_except, true);
  const tool = normalizeContent({ ...routed, actions: ["receive_tool_result"] });
  assert.deepEqual([tool.outcome.kind, tool.content.sticky], ["mask", false], "tool results fall back to Mask");
  const gone = normalizeContent({ ...routed, content: { ...routed.content, detectors: ["iban"] }, actions: ["run_command"] });
  assert.deepEqual([gone.content.detectors, gone.outcome.kind], [[], "block"], "no content action, no content");
});

test("approved models: chips follow the categories; a target no longer approved is cleared", () => {
  assert.deepEqual(categoriesOf(["iban", "custom.ref", "iban"], DETECTORS), ["pii", "confidential_identifier"]);
  assert.deepEqual(approvedAliases(ALIASES, ["pii"]).map((item) => item.approved), [true, false]);
  const routed = { ...withOutcome(model({ content: { detectors: ["iban"], sticky: true, incomplete: false } }), "reroute") };
  const target = { ...routed, outcome: { ...routed.outcome, reroute_to: "approved-model" } };
  assert.equal(toggleDetector(target, "email", DETECTORS, ALIASES).outcome.reroute_to, "approved-model");
  assert.equal(toggleDetector(target, "custom.ref", DETECTORS, ALIASES).outcome.reroute_to, "");
  assert.deepEqual(effectBadge(target), { label: "Routes", tone: "running" });
  assert.deepEqual(effectBadge(withOutcome(target, "mask_reroute")), { label: "Masks · routes", tone: "running" });
  assert.deepEqual(effectBadge(model({ actions: ["run_command"] })), { label: "Blocks", tone: "danger" });
  assert.equal(routeTargetWarning(target, 6), null);
  assert.equal(routeTargetWarning(routed, 6, true), "Pick the approved model in step 6 (Outcome) — the only required input of this template.");
});

test("model and catalog: content sections read from the server; templates open on the missing input", () => {
  const read = readModel({ id: "x", actions: ["call_model"], content: { detectors: ["iban"], sticky: true, categories: ["pii"] },
    outcome: { kind: "teleport", reroute_to: "m" } });
  assert.deepEqual(read.content, { detectors: ["iban"], sticky: true, incomplete: false }, "derived categories are the server's");
  assert.equal(read.outcome.kind, "block");
  assert.deepEqual(catalog.outcomes.map((item) => item.id), ["block", "mask", "reroute", "mask_reroute"]);
  assert.equal(catalog.actions.find((item) => item.id === "call_model").content, "request body");
  assert.equal(catalog.templates.filter((item) => item.section === "Sensitive data in requests and tool results").length, 5);
  assert.equal(startStep(fromTemplate(ROUTED_TEMPLATE), ROUTED_CATALOG), "outcome");
  assert.equal(startStep(fromTemplate(template("workspace-identifiers-approved-model")), catalog), "content");
  assert.equal(startStep(fromTemplate(template("secrets-never-leave")), catalog), "check");
});

test("preview: the server's parts are shown masked only for mask outcomes and only for the chosen detectors", () => {
  const preview = readContentPreview({ counts: { iban: 1, email: 2, bad: "x" }, parts: [{ text: "account " }, { text: "CH93", detector: "iban", masked: true, placeholder: "[IBAN #1]" }] });
  assert.deepEqual(preview.counts, { iban: 1, email: 2 });
  const part = preview.parts[1];
  const chosen = model({ content: { detectors: ["iban"], sticky: false, incomplete: false } });
  assert.deepEqual(previewMark(part, withOutcome(chosen, "mask")), { shown: "[IBAN #1]", mark: "hit" });
  assert.deepEqual(previewMark(part, chosen), { shown: "CH93", mark: "blocked" });
  assert.deepEqual(previewMark(part, model()), { shown: "CH93", mark: "none" });
});

test("builder page: a mask-and-route policy — Outcome first, only approved aliases, server preview with the chosen detectors", async () => {
  const srv = server((call) => {
    const url = call.url.replace("/api/v1/admin/policy-engine", "");
    if (url === "/content-detectors") return { status: 200, body: { categories: [{ id: "pii", label: "Personal data" }], detectors: [
      { id: "email", category: "pii", label: "Email address", method: "local@domain.tld", builtin: true },
      { id: "phone", category: "pii", label: "Phone number", method: "E.164", builtin: true },
      { id: "iban", category: "pii", label: "IBAN", method: "ISO 7064 mod-97", builtin: true }] } };
    if (url === "/content-detectors/preview") return { status: 200, body: { counts: { iban: 2 }, parts: [{ text: "x" }], truncated: false } };
    if (url === "/policy-builder/render") return { status: 200, body: { valid: true, issues: [], text: "", sentence: [], scope: "", warnings: [] } };
    return { status: 404, body: {} };
  });
  const { PolicyBuilder } = load("admin/components/policyEngine/PolicyBuilder.tsx", { fetch: srv.fetch, window: undefined });
  const entities = readPickerEntities({ model_aliases: [
    { alias: "approved-model", data_policy_class: "restricted", approved_for: ["pii"] }, { alias: "general-model", data_policy_class: "internal", approved_for: [] }] });
  const session = { model: fromTemplate(ROUTED_TEMPLATE), isNew: true, title: "New policy", originalId: null };
  const view = { version: null, publishedVersion: null, authorName: "", items: [], generated: null, changes: { new: 0, changed: 0, removed: 0 },
    editTarget: { version: 0, digest: "sha256:empty", createsDraft: true } };
  let page;
  await act(async () => { page = TestRenderer.create(createElement(PolicyBuilder, { session, catalog: ROUTED_CATALOG, entities, view, previewDelay: 0,
    onCancel: () => {}, onSaved: async () => {}, onEditAsCedar: () => {}, checkStep: () => null })); });
  for (let index = 0; index < 3; index += 1) await tick();
  assert.equal(byTestId(page, "builder-pane-outcome").length, 1, "opens on the missing approved model");
  assert.equal(text(byTestId(page, "builder-effect")[0]), "Masks · routes");
  assert.match(text(byTestId(page, "builder-route-warning")[0]), /step 6 \(Outcome\) — the only required input/);
  const targets = byTestId(page, "builder-route-target");
  assert.deepEqual(targets.map((node) => [node.props["data-value"], node.props.disabled]), [["approved-model", false], ["general-model", true]]);
  assert.match(text(targets[1]), /not approved/);
  assert.equal(byTestId(page, "builder-outcome-reroute")[0].props.disabled, false);
  await act(async () => { targets[0].props.onClick(); });
  await tick();
  assert.equal(byTestId(page, "builder-route-warning").length, 0);
  const rendered = srv.calls.filter((call) => call.url.endsWith("/policy-builder/render")).at(-1).body.model;
  assert.equal(rendered.outcome.reroute_to, "approved-model");

  await act(async () => { byTestId(page, "builder-step-content")[0].props.onClick(); });
  assert.equal(byTestId(page, "builder-detector").length, 3);
  await change(page, "builder-content-sample", "synthetic text");
  for (let index = 0; index < 3; index += 1) await tick();
  const asked = srv.calls.filter((call) => call.url.endsWith("/content-detectors/preview")).at(-1).body;
  assert.deepEqual(asked, { text: "synthetic text", mask: ["email", "phone", "iban"], mask_style: "type_token" });
  assert.equal(text(byTestId(page, "builder-detector-count-iban")[0]), "2");
  assert.equal(srv.calls.some((call) => call.url.endsWith("/policy-builder/render") && JSON.stringify(call.body).includes("synthetic")), false,
    "the example never enters the model");
});

test("the policy list's Effect shows a content policy's obligation like the builder badge", async () => {
  const { effectOf, readPolicyItem } = await import("../../src/admin/components/policyEngine/policyCatalogModel.ts");
  const item = (effect, model) => readPolicyItem({ id: "p1", name: "P", effect, model });
  const content = (kind) => ({ actions: ["call_model"], content: { detectors: ["iban"] }, outcome: { kind } });
  assert.deepEqual(effectOf(item("forbid", content("mask_reroute"))), { label: "Masks · routes", tone: "running" });
  assert.equal(effectOf(item("forbid", content("mask"))).label, "Masks");
  assert.equal(effectOf(item("forbid", content("reroute"))).label, "Routes");
  assert.deepEqual(effectOf(item("forbid", content("block"))), { label: "Blocks", tone: "danger" });
  assert.deepEqual(effectOf(item("forbid", null)), { label: "Blocks", tone: "danger" });
  assert.deepEqual(effectOf(item("permit", null)), { label: "Allows", tone: "active" });
});
