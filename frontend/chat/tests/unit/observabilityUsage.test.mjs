// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityUsage.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { axisTop, percent, unpricedModels, unpricedShare } from "../../src/admin/components/observability/usageModel.ts";

test("priced coverage and the unpriced share are stated, unknown is a dash", () => {
  assert.equal(percent(0.82), "82 %");
  assert.equal(percent(null), "–");
  assert.equal(unpricedShare({ platform_billed_tokens: 1000, unpriced_tokens: 180 }), 0.18);
  assert.equal(unpricedShare({ platform_billed_tokens: 0, unpriced_tokens: 0 }), 0);
});

test("only unpriced models feed the pricing warning; seat models are not unpriced", () => {
  const rows = [
    { provider: "bedrock", model: "a", tokens: 10, unpriced_tokens: 10, cost: 0, pricing: "unpriced" },
    { provider: "anthropic_seat", model: "b", tokens: 10, unpriced_tokens: 0, cost: 0, pricing: "not_billed" },
    { provider: "litellm_gateway", model: "c", tokens: 10, unpriced_tokens: 0, cost: 1, pricing: "priced" },
  ];
  assert.deepEqual(unpricedModels(rows).map((row) => row.model), ["a"]);
});

test("the trend axis starts at zero and tops above the maximum", () => {
  assert.equal(axisTop([]), 1);
  assert.equal(axisTop([0, 0]), 1);
  assert.equal(axisTop([171, 40]), 200);
  assert.equal(axisTop([3.2]), 5);
});

test("the unpriced-model policy lives on Runtime → Limits & budgets, next to the cost caps it governs", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../../src/admin/components/limits/AdminLimitsAndBudgets.tsx", import.meta.url), "utf8");
  const field = await readFile(new URL("../../src/admin/components/limits/UnpricedModelPolicyField.tsx", import.meta.url), "utf8");
  assert.match(page, /<UnpricedModelPolicyField \/>/);
  assert.match(field, /\/api\/v1\/admin\/runtime\/unpriced-model-policy/);
  assert.match(field, /Runtime → Model catalog/);
});
