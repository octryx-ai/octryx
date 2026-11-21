// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/contentDetectors.test.mjs
//
// Detectors tab and the alias field "Approved for sensitive data": the custom detector id follows the name
// until edited, confidence is derived like the backend, the save body never carries the test text, the category
// filter, and the alias catalog entry round-trips approved categories and refuses malformed ones.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import {
  buildDetectorsBody, detectorConfidence, detectorIdFor, draftProblem, emptyDetector, filterDetectors, parseContextWords,
  previewBody, readDetectorCatalog, slugOf,
} from "../../src/admin/components/policyEngine/detectorsModel.ts";
import { buildGatewayUpdatePayload } from "../../src/admin/components/providerTab/litellmGatewayPayload.ts";
import { gatewayDraftFromProvider } from "../../src/admin/components/providerTab/litellmGatewayDrafts.ts";
import { gatewayValidationCodes } from "../../src/admin/components/providerTab/litellmGatewayValidation.ts";
import { act, byTestId, change, click, load, server, tick } from "./policyEngineHarness.mjs";

const CATALOG = readDetectorCatalog({
  version: 3, state: "draft", digest: "sha256:x",
  categories: [{ id: "pii", label: "Personal data", builtin: true }, { id: "contracts", label: "Contracts", builtin: false }],
  detectors: [
    { id: "iban", category: "pii", label: "IBAN", method: "Country code, per-country length, ISO 7064 mod-97", confidence: "high", mask_styles: ["country_last4", "type_token"], builtin: true, used_by: [] },
    { id: "custom.case_ref", category: "contracts", label: "Case reference", method: "RE2 pattern", confidence: "high", mask_styles: ["last4"],
      builtin: false, used_by: ["names-case-ref"], pattern: "\\d+", check: "none", context_words: ["case"], mask_style: "last4", workspace_id: null },
  ],
});

test("the id follows the name as custom.<slug> until the admin edits it", () => {
  assert.equal(detectorIdFor("Customer Reference", "", false), "custom.customer_reference");
  assert.equal(detectorIdFor("  42 Café-Nr. ", "", false), "custom.cafe_nr");
  assert.equal(detectorIdFor("Renamed", "custom.kept", true), "custom.kept");
  assert.equal(detectorIdFor("1", "", false), "");
  assert.equal(slugOf("x".repeat(60)).length, 40);
});

test("confidence is high with a check or keywords, else medium", () => {
  assert.equal(detectorConfidence({ check: "none", contextWords: [] }), "medium");
  assert.equal(detectorConfidence({ check: "mod10", contextWords: [] }), "high");
  assert.equal(detectorConfidence({ check: "none", contextWords: parseContextWords("ref, Customer,ref") }), "high");
  assert.deepEqual(parseContextWords("ref, Customer,ref"), ["ref", "customer"]);
  const stored = readDetectorCatalog({ categories: [], detectors: [{ id: "custom.ref", category: "pii", label: "Ref", builtin: false,
    pattern: "\\d+", check: "mod10", context_words: [], mask_style: "last4" }] });
  assert.equal(stored.detectors[0].custom.check, "mod10", "the stored check is read as it is");
});

test("the save body is the definitions and admin categories only, never the test text", () => {
  const detector = { ...emptyDetector("contracts"), id: "custom.order_no", label: " Order number ", pattern: "\\d{6}" };
  const withText = { ...detector, test: "synthetic sample 123456" };
  const body = buildDetectorsBody([CATALOG.detectors[1].custom, withText], CATALOG.categories);
  assert.deepEqual(body.categories, [{ id: "contracts", label: "Contracts" }]);
  assert.deepEqual(Object.keys(body.detectors[1]).sort(),
    ["category", "check", "context_words", "id", "label", "mask_style", "pattern", "workspace_id"]);
  assert.equal(body.detectors[1].label, "Order number");
  assert.ok(!JSON.stringify(body).includes("synthetic sample"));
  // The preview sends the text per request, and only there.
  const preview = previewBody(detector, CATALOG.categories, "synthetic sample 123456");
  assert.equal(preview.text, "synthetic sample 123456");
  assert.ok(!JSON.stringify(preview.detectors).includes("synthetic sample"));
});

test("the category filter and search narrow the table", () => {
  assert.deepEqual(filterDetectors(CATALOG.detectors, "", "contracts").map((row) => row.id), ["custom.case_ref"]);
  assert.deepEqual(filterDetectors(CATALOG.detectors, "mod-97", "").map((row) => row.id), ["iban"]);
  assert.equal(filterDetectors(CATALOG.detectors, "", "").length, 2);
  assert.deepEqual(CATALOG.detectors[1].usedBy, ["names-case-ref"]);
});

test("the form refuses an incomplete or duplicate definition before the server does", () => {
  const others = [CATALOG.detectors[1].custom];
  const base = { ...emptyDetector("pii"), id: "custom.order_no", label: "Order", pattern: "\\d+" };
  assert.equal(draftProblem(base, others, null), null);
  assert.match(draftProblem({ ...base, id: "custom.case_ref" }, others, null), /already has this id/);
  assert.match(draftProblem({ ...base, id: "order" }, others, null), /custom\./);
  assert.match(draftProblem({ ...base, pattern: "x".repeat(301) }, others, null), /300/);
  assert.match(draftProblem(base, others, { id: "contracts", label: "Contracts" }, CATALOG.categories), /already exists/);
});

test("approved categories round-trip through the alias catalog and malformed ones are refused", () => {
  const provider = { display_name: "gw", endpoint_url: "https://gw", config_json: { litellm_gateway: { aliases: { "company-model": {
    model_group: "g", context_limit: 1000, data_policy_class: "restricted", capabilities: {}, cost: { source: "governed_free", contract_reference: "R" },
    approved_data_categories: ["pii", "health"] } } } } };
  const draft = gatewayDraftFromProvider(provider);
  assert.deepEqual(draft.aliases[0].approvedDataCategories, ["health", "pii"]);
  const entry = buildGatewayUpdatePayload(draft, provider.config_json).config_json.litellm_gateway.aliases["company-model"];
  assert.deepEqual(entry.approved_data_categories, ["health", "pii"]);
  const none = { ...draft, aliases: [{ ...draft.aliases[0], approvedDataCategories: [] }] };
  assert.ok(!("approved_data_categories" in buildGatewayUpdatePayload(none, {}).config_json.litellm_gateway.aliases["company-model"]));
  const bad = { ...draft, aliases: [{ ...draft.aliases[0], approvedDataCategories: ["Health data"] }] };
  assert.deepEqual(gatewayValidationCodes(bad).aliases, [{ index: 0, codes: ["alias_approved_data_categories_invalid"] }]);
});

const RAW_CATALOG = {
  version: 3, state: "draft", digest: "sha256:d3",
  categories: [{ id: "contracts", label: "Contracts", builtin: false }],
  detectors: [{ id: "custom.case_ref", category: "contracts", label: "Case reference", method: "RE2 pattern", confidence: "high",
    mask_styles: ["last4"], builtin: false, used_by: [], pattern: "\\d+", check: "none", context_words: ["case"], mask_style: "last4", workspace_id: null }],
};

async function renderTab(target) {
  const srv = server((call) => (call.url.endsWith("/content-detectors") ? { status: 200, body: RAW_CATALOG }
    : call.url.endsWith("/preview") ? { status: 200, body: { counts: { "custom.case_ref": 1 }, masked_text: "case [CASE_REF #1]" } }
      : call.method === "PUT" ? { status: 200, body: {} } : { status: 404, body: {} }));
  const { AdminDetectors } = load("admin/components/policyEngine/AdminDetectors.tsx", { fetch: srv.fetch, window: undefined });
  const saved = [];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminDetectors, { target, workspaces: [], previewDelay: 0, onSaved: async (text) => { saved.push(text); } })); });
  await tick();
  return { view, srv, saved };
}

test("drawer: the test text goes to the preview only; Save to draft PUTs the definitions with the draft digest", async () => {
  const { view, srv, saved } = await renderTab({ version: 3, digest: "sha256:d3", createsDraft: false });
  await act(async () => { byTestId(view, "detector-row")[0].props.onClick(); });
  await change(view, "detector-test", "synthetic case 42");
  await tick();
  const preview = srv.calls.find((call) => call.url.endsWith("/preview"));
  assert.equal(preview.body.text, "synthetic case 42");
  assert.equal(byTestId(view, "detector-test-masked").length, 1);
  await click(view, "detector-save");
  await tick();
  const put = srv.calls.find((call) => call.method === "PUT");
  assert.ok(put.url.endsWith("/policy-sets/3/detectors"));
  assert.equal(put.headers["If-Match"], "sha256:d3");
  assert.ok(!JSON.stringify(put.body).includes("synthetic"));
  assert.equal(saved.length, 1);
});

test("drawer: a frozen draft in review is read-only", async () => {
  const { view } = await renderTab(null);
  assert.equal(byTestId(view, "detectors-new")[0].props.disabled, true);
  await act(async () => { byTestId(view, "detector-row")[0].props.onClick(); });
  assert.equal(byTestId(view, "detector-save")[0].props.disabled, true);
  assert.equal(byTestId(view, "detector-delete")[0].props.disabled, true);
});
