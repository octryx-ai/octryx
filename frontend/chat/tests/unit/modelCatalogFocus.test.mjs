// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelCatalogFocus.test.mjs
//
// A Problems link (E5, "model has no price") lands on the model: ?model=<id> opens that catalog row once.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { focusedModelId, modelToFocus } from "../../src/admin/components/modelCatalog/modelFocus.ts";

const models = [
  { id: "row-1", catalogKey: "bedrock/claude-sonnet", modelId: "anthropic.claude-sonnet" },
  { id: "row-2", catalogKey: "openai/gpt-x", modelId: "gpt-x" },
];

test("the address names the model; nothing without it", () => {
  assert.equal(focusedModelId("?area=admin&tab=modelCatalog&model=row-2"), "row-2");
  assert.equal(focusedModelId("?area=admin&tab=modelCatalog"), "");
  assert.equal(focusedModelId(undefined), "");
});

test("the row is found by its id first, else by catalog key or model id; an unknown id is ignored", () => {
  assert.equal(modelToFocus(models, "?model=row-2")?.id, "row-2");
  assert.equal(modelToFocus(models, "?model=bedrock/claude-sonnet")?.id, "row-1");
  assert.equal(modelToFocus(models, "?model=gpt-x")?.id, "row-2");
  assert.equal(modelToFocus(models, "?model=missing"), null);
  assert.equal(modelToFocus(models, ""), null);
  assert.equal(modelToFocus([], "?model=row-1"), null);
});

test("the catalog opens the named model only once (a later reload does not reopen it)", () => {
  const source = readFileSync(new URL("../../src/admin/components/modelCatalog/AdminModelCatalog.tsx", import.meta.url), "utf8");
  assert.match(source, /const focused = useRef\(false\)/);
  assert.match(source, /if \(focused\.current \|\| !catalog\) return;/);
  assert.match(source, /focused\.current = true;[^}]*setOpenId\(target\.id\)/);
  // A linked model that the default view (used or enabled) hides is shown with all models, so its row is there.
  assert.match(source, /if \(!filterRows\(\[target\], "", "", "inUse"\)\.length\) setScope\("all"\);/);
});
