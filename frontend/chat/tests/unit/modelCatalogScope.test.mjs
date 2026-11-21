// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelCatalogScope.test.mjs
//
// UI check (C6), Admin › Models › Catalog: 43 Bedrock models stood first although Bedrock is
// disabled, the 6 used models at the bottom, and models of the disabled provider read "Needs attention". The catalog
// now opens on the used and enabled models (used first), "All models" shows every one, and only a model at an active
// provider can need attention.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  filterRows,
  inUse,
  needsAttention,
  readCatalog,
  sortRows,
  statusView,
} from "../../src/admin/components/modelCatalog/modelCatalogContract.ts";
import { byTestId, click, render, server, text } from "./settingsRenderHarness.mjs";

const GATEWAY = { id: "gw", display_name: "LiteLLM", is_gateway: true, is_active: true };
const BEDROCK = { id: "br", display_name: "Bedrock", is_gateway: false, is_active: false };

function raw(id, overrides = {}) {
  return {
    id, catalog_key: id, model_id: id, display_name: id, provider: GATEWAY, enabled: true,
    capabilities: {}, cleared_up_to: "internal", approved_data_categories: [], temperature: null, max_output_tokens: null,
    context_length: null, cost: {}, used_by_workspaces: 0, order_position: null, status: "enabled", issues: [], ...overrides,
  };
}

// Like: Bedrock models (enabled, provider off, flagged) listed first by the server, the used ones last.
const PAYLOAD = {
  models: [
    raw("bedrock-a", { provider: BEDROCK, status: "needs_attention", issues: [{ code: "provider_off", detail: "" }] }),
    raw("bedrock-b", { provider: BEDROCK, enabled: false, status: "off" }),
    raw("gw-off", { enabled: false, status: "off" }),
    raw("gw-enabled"),
    raw("gw-used-2", { used_by_workspaces: 1, order_position: 2 }),
    raw("gw-used-1", { used_by_workspaces: 3, order_position: 1 }),
  ],
  providers: [GATEWAY, BEDROCK],
};
const rows = () => readCatalog(PAYLOAD).models;
const ids = (list) => list.map((row) => row.id);

test("A model of a disabled provider never needs attention; it reads Provider off with the reason", () => {
  const [bedrock] = rows();
  assert.equal(needsAttention(bedrock), false);
  assert.deepEqual(statusView(bedrock), { label: "Provider off", tone: "neutral", title: "The provider connection is disabled" });
  const flagged = readCatalog({ models: [raw("x", { status: "needs_attention", issues: [{ code: "not_cleared", detail: "" }] })] }).models[0];
  assert.equal(statusView(flagged).label, "Needs attention", "an active provider's model still does");
  const offWithoutCode = readCatalog({ models: [raw("y", { provider: BEDROCK })] }).models[0];
  assert.equal(statusView(offWithoutCode).title, "The provider connection is disabled");
});

test("The default view keeps used models and enabled ones at an active provider, used first in platform order", () => {
  assert.deepEqual(ids(rows().filter(inUse)), ["gw-enabled", "gw-used-2", "gw-used-1"]);
  assert.deepEqual(ids(sortRows(filterRows(rows(), "", "", "inUse"))), ["gw-used-1", "gw-used-2", "gw-enabled"]);
  assert.deepEqual(ids(sortRows(filterRows(rows(), "", "", "all"))),
    ["gw-used-1", "gw-used-2", "gw-enabled", "bedrock-a", "bedrock-b", "gw-off"]);
  // Enabled means usable: a model at a disabled provider is not counted as enabled, and no Bedrock row needs attention.
  assert.deepEqual(ids(filterRows(rows(), "", "on")), ["gw-enabled", "gw-used-2", "gw-used-1"]);
  assert.deepEqual(ids(filterRows(rows(), "", "issue")), []);
  assert.deepEqual(ids(filterRows(rows(), "br", "", "inUse")), []);
});

test("rendered: opens on Used or enabled, offers the hidden models in one click, and All models shows them", async () => {
  const srv = server((call) => (call.url.includes("model-catalog") ? { status: 200, body: PAYLOAD } : { status: 200, body: { detectors: [] } }));
  const view = await render("admin/components/modelCatalog/AdminModelCatalog.tsx", "AdminModelCatalog", srv);
  const shown = () => view.root.findAll((node) => node.type === "tr" && String(node.props["data-testid"] || "").startsWith("catalog-row-"))
    .map((node) => node.props["data-testid"].replace("catalog-row-", ""));
  assert.deepEqual(shown(), ["gw-used-1", "gw-used-2", "gw-enabled"]);
  assert.match(text(byTestId(view, "catalog-scope")[0]), /Used or enabled\s*3.*All models\s*6/);
  assert.doesNotMatch(text(byTestId(view, "catalog-table")[0]), /Needs attention/);
  assert.equal(text(byTestId(view, "catalog-show-all")[0]), "Show 3 more models (off or at a disabled provider)");
  await click(view, "catalog-show-all");
  assert.deepEqual(shown(), ["gw-used-1", "gw-used-2", "gw-enabled", "bedrock-a", "bedrock-b", "gw-off"]);
  assert.equal(byTestId(view, "catalog-show-all").length, 0);
  assert.match(text(byTestId(view, "catalog-table")[0]), /Provider off/);
  assert.doesNotMatch(text(byTestId(view, "catalog-table")[0]), /Needs attention/);
  view.unmount();
});
