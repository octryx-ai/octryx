// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelCatalogContract.test.mjs
//
// Runtime → Models → Model catalog (S1): one row per callable model, the drawer
// sends only what changed, clearance raises are detected, sync results are read without echoing raw payloads.

import assert from "node:assert/strict";
import { test } from "node:test";

import { catalogPatch, draftFromRow, draftProblems, filterRows, isClearanceRaise, priceText, readCatalog, saveErrorText, statusView } from "../../src/admin/components/modelCatalog/modelCatalogContract.ts";
import { readSyncResult } from "../../src/admin/components/modelCatalog/modelCatalogSync.ts";

const LEVELS = ["public", "internal", "confidential", "restricted"];

function rawRow(overrides = {}) {
  return {
    id: "m1", catalog_key: "model-a", model_id: "model-a", display_name: "Model A",
    provider: { id: "p1", display_name: "Provider One", is_gateway: true, is_active: true },
    enabled: true, capabilities: { tools: true, vision: false, coding: true, long_context: false },
    cleared_up_to: "internal", approved_data_categories: ["pii"], temperature: null, max_output_tokens: null,
    context_length: 200000,
    cost: { pricing_input: 3, pricing_output: 15, cost_source: "catalog_pricing", contract_reference: "", editable: true },
    used_by_workspaces: 2, order_position: 1, status: "enabled", issues: [],
    ...overrides,
  };
}

test("the catalog payload is read into typed rows; malformed rows are dropped", () => {
  const catalog = readCatalog({ models: [rawRow(), { display_name: "no id" }], providers: [{ id: "p1", display_name: "Provider One" }],
    clearance_levels: LEVELS });
  assert.equal(catalog.models.length, 1);
  const [row] = catalog.models;
  assert.equal(row.displayName, "Model A");
  assert.deepEqual(row.capabilities, { tools: true, vision: false, coding: true, long_context: false });
  assert.equal(priceText(row), "$3.00 · $15.00");
  assert.deepEqual(catalog.levels, LEVELS);
});

test("an unchanged draft saves nothing; a change sends only its own field", () => {
  const [row] = readCatalog({ models: [rawRow()], clearance_levels: LEVELS }).models;
  const draft = draftFromRow(row);
  assert.deepEqual(catalogPatch(row, draft), {});
  assert.deepEqual(catalogPatch(row, { ...draft, clearedUpTo: "confidential" }), { cleared_up_to: "confidential" });
  assert.deepEqual(catalogPatch(row, { ...draft, maxOutputTokens: "" }), {});
  assert.deepEqual(catalogPatch(row, { ...draft, temperature: 0.2 }), { temperature: 0.2 });
});

test("a direct model's context window is saved and checked; a gateway model's is not sent", () => {
  const [gateway] = readCatalog({ models: [rawRow()], clearance_levels: LEVELS }).models;
  assert.deepEqual(catalogPatch(gateway, { ...draftFromRow(gateway), contextLength: "1000000" }), {});
  const [direct] = readCatalog({ models: [rawRow({ provider: { id: "p2", display_name: "Bedrock", is_gateway: false, is_active: true },
    context_length: null })], clearance_levels: LEVELS }).models;
  const draft = draftFromRow(direct);
  assert.equal(draft.contextLength, "");
  assert.deepEqual(catalogPatch(direct, { ...draft, contextLength: "1000000" }), { context_length: 1000000 });
  assert.deepEqual(draftProblems({ ...draft, contextLength: "500" }, direct).length, 1);
  assert.deepEqual(draftProblems({ ...draft, contextLength: "1000000" }, direct), []);
});

test("raising the clearance is detected, lowering is not", () => {
  const [row] = readCatalog({ models: [rawRow()], clearance_levels: LEVELS }).models;
  const draft = draftFromRow(row);
  assert.equal(isClearanceRaise(row, { ...draft, clearedUpTo: "confidential" }, LEVELS), true);
  assert.equal(isClearanceRaise(row, { ...draft, clearedUpTo: "public" }, LEVELS), false);
  assert.equal(isClearanceRaise(row, { ...draft, clearedUpTo: null }, LEVELS), false);
});

test("draft problems are worded before the server refuses", () => {
  const [row] = readCatalog({ models: [rawRow()], clearance_levels: LEVELS }).models;
  const draft = draftFromRow(row);
  assert.deepEqual(draftProblems(draft, row), []);
  assert.equal(draftProblems({ ...draft, displayName: " " }, row).length, 1);
  assert.equal(draftProblems({ ...draft, pricingInput: "0" }, row).length, 1);
});

test("status filter and status view: needs attention names the issue; a model that is off is just Off", () => {
  const rows = readCatalog({ models: [rawRow(), rawRow({ id: "m2", enabled: false, status: "needs_attention",
    issues: [{ code: "no_alias", detail: "" }] }), rawRow({ id: "m3", enabled: true, status: "needs_attention",
    issues: [{ code: "not_cleared", detail: "" }] })] }).models;
  assert.deepEqual(filterRows(rows, "", "issue").map((row) => row.id), ["m3"]);
  assert.deepEqual(filterRows(rows, "", "on").map((row) => row.id), ["m1", "m3"]);
  assert.deepEqual(filterRows(rows, "", "off").map((row) => row.id), ["m2"]);
  // A disabled model is neutral "Off"; what would stop it stays in the tooltip.
  assert.deepEqual(statusView(rows[1]), { label: "Off", tone: "neutral", title: "Not callable: no gateway alias" });
  assert.deepEqual(statusView(rows[2]), { label: "Needs attention", tone: "attention", title: "Enabled, but not cleared for any data class" });
});

test("sync results and save errors never echo raw server text for known codes", () => {
  const sync = readSyncResult({ new: [{ provider_id: "p1", provider: "Provider One", model_id: "x", supports_tools: true }],
    gone: [{ id: "m3", display_name: "Old", enabled: true }], providers: [{ provider: "Provider Two", state: "failed" }] });
  assert.equal(sync.proposals[0].meta, "Provider One · tools");
  assert.deepEqual(sync.failed, ["Provider Two"]);
  assert.equal(saveErrorText({ detail: { code: "model_catalog_temperature_invalid" } }),
    "Not saved: the temperature must be between 0 and 2.");
});
