// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelsOverview.test.mjs
//
// Global › Models (UX audit Welle 2): providers in one form, models with price and what the workspaces
// narrowed. The global level defines; a workspace only narrows, and the overview shows every narrowing.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  availableText,
  priceText,
  providerModelsLine,
  providerState,
  workspaceChanges,
} from "../../src/admin/components/modelsOverview/modelsOverviewModel.ts";

const provider = { id: "p", name: "LiteLLM (company gateway)", driver: "litellm", endpoint: "litellm.gateway", state: "connected",
  error: null, models_found: 14, models_on: 6, loaded_at: null };
const model = { key: "gemma", label: "Gemma 4 31B", provider: "LiteLLM (company gateway)", price_in: 0.14, price_out: 0.4,
  cost_source: "gateway_reported", available_in: 5, off_in: [], default_in: [], platform_default: true };

test("a provider says its state and its models in one line", () => {
  assert.equal(providerState(provider).label, "Connected");
  assert.equal(providerModelsLine(provider), "14 models found · 6 switched on");
  assert.equal(providerState({ ...provider, state: "off" }).label, "Switched off");
  assert.match(providerModelsLine({ ...provider, state: "off" }), /not offered/);
  assert.equal(providerModelsLine({ ...provider, models_found: 0 }), "No models loaded yet.");
});

test("models show price, availability and every workspace narrowing", () => {
  assert.equal(priceText(model), "$0.14 / $0.40");
  assert.equal(priceText({ ...model, price_out: null }), null);
  assert.equal(availableText(model, 5), "All 5");
  assert.equal(availableText({ ...model, available_in: 2 }, 5), "Selected: 2");
  assert.equal(availableText({ ...model, available_in: 0 }, 5), "None");
  assert.equal(workspaceChanges(model), "none");
  assert.equal(workspaceChanges({ ...model, default_in: ["Risk Team"] }), "Default in “Risk Team”");
  // A workspace called "default" must not read as a word of the sentence.
  assert.equal(workspaceChanges({ ...model, off_in: ["default"] }), "Off in “default”");
  assert.equal(workspaceChanges({ ...model, off_in: ["A", "B"] }), "Off in 2 workspaces");
  assert.equal(availableText({ ...model, provider_off: true }, 5), "Not offered: provider switched off");
});
