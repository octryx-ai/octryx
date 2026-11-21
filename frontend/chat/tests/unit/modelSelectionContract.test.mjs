// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelSelectionContract.test.mjs
//
// Runtime → Models → Default & fallback (S2): one platform order of catalog
// models, two fallback choices (no driver default), task models; the four removed pages redirect here.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  listAdminAreaTabRefs,
  resolveAdminAreaForTab,
  resolveAdminAreaTab,
  resolveAdminSidebarTab,
} from "../../src/admin/config/adminPanelAreas.ts";
import {
  FALLBACK_CHOICES,
  TRACE_MARK,
  addableModels,
  explainBody,
  explainFailed,
  readExplainOptions,
  readExplainResult,
  moveEntry,
  orderSubline,
  readSelectionPage,
  selectionErrorText,
  taskPayload,
} from "../../src/admin/components/modelSelection/modelSelectionContract.ts";
import { ADMIN_ENTRIES, locateAdminPage } from "../../src/admin/config/adminEntries.ts";

const model = (key, extra = {}) => ({
  catalog_key: key, display_name: key.toUpperCase(), provider: "Provider One", enabled: true, provider_active: true,
  cleared_up_to: "internal", capabilities: { tools: true }, ...extra,
});

test("the page payload is read; an unknown fallback reads as the next allowed model", () => {
  const page = readSelectionPage({ order: [model("a"), { display_name: "no key" }], fallback: "driver_default",
    tasks: [{ key: "summarize", label: "Conversation summaries", model_key: null, workspace_overrides: 2 }],
    models: [model("a"), model("b"), model("c", { enabled: false })] });
  assert.deepEqual(page.order.map((item) => item.key), ["a"]);
  assert.equal(page.fallback, "next");
  assert.deepEqual(page.tasks[0], { key: "summarize", label: "Conversation summaries", modelKey: null, workspaceOverrides: 2 });
  assert.equal(orderSubline(page.order[0]), "Provider One · cleared up to Internal");
  assert.deepEqual(addableModels(page, ["a"]).map((item) => item.key), ["b"]);
});

test("there are exactly two fallback choices", () => {
  assert.deepEqual(FALLBACK_CHOICES.map((choice) => choice.value), ["next", "stop"]);
});

test("moving an entry swaps neighbours and ignores moves past the ends", () => {
  assert.deepEqual(moveEntry(["a", "b", "c"], 1, -1), ["b", "a", "c"]);
  assert.deepEqual(moveEntry(["a", "b", "c"], 2, 1), ["a", "b", "c"]);
  assert.deepEqual(moveEntry(["a", "b", "c"], 0, -1), ["a", "b", "c"]);
});

test("an empty task choice is sent as the platform default (null)", () => {
  assert.deepEqual(taskPayload({ summarize: "", judge: "a" }), { summarize: null, judge: "a" });
});

test("refusals are worded from fixed codes", () => {
  assert.equal(selectionErrorText({ detail: { code: "model_order_model_not_enabled" } }),
    "Not saved: a model in the order is not enabled in the Model catalog.");
  assert.equal(selectionErrorText({ detail: { code: "anything else" } }), "Not saved: the change was refused.");
});

test("Default & fallback is the one model order page", () => {
  const visible = listAdminAreaTabRefs("admin").filter((ref) => !ref.hidden).map((ref) => ref.id);
  for (const retired of ["runtimes", "runtimeDefaults", "runtimeRouting", "runtimeFallback"]) {
    assert.equal(visible.includes(retired), false);
    assert.notEqual(resolveAdminAreaTab("admin", retired), retired);
  }
  assert.equal(resolveAdminAreaForTab("modelOrder"), "admin");
  // Models is one entry; Providers, Catalog, Defaults and Budgets are its views.
  const models = ADMIN_ENTRIES.find((entry) => entry.label === "Models");
  assert.deepEqual(models.views.map((view) => view.pages[0].tab), ["modelsOverview", "providers", "modelCatalog", "modelOrder", "runtimeLimits"]);
  assert.equal(resolveAdminSidebarTab("admin", "runtimePolicyLists"), "modelsOverview");
  assert.equal(locateAdminPage("runtimePolicyLists").page.tab, "modelOrder");
});

test("Explain a turn: the form body, the options and the result are read without trusting unknown values", () => {
  assert.deepEqual(explainBody({ workspaceId: "w1", personChoice: "", agentPin: "a", firstFails: false }),
    { workspace_id: "w1", person_choice: "", agent_pin: "a", first_fails: false });
  const options = readExplainOptions({ workspaces: [{ id: "w1", name: "Claims Desk", data_class: "confidential" }, { name: "x" }],
    models: [{ key: "large", name: "Orion Large" }] });
  assert.deepEqual(options.workspaces, [{ id: "w1", name: "Claims Desk", dataClass: "confidential" }]);
  const result = readExplainResult({ state: "refused", title: "Refused · Fast", note: "n",
    trace: [{ icon: "ok", label: "Allowed", text: "t" }, { icon: "weird", label: "Start", text: "s" }] });
  assert.equal(explainFailed(result.state), true);
  assert.deepEqual(result.trace.map((step) => TRACE_MARK[step.icon]), ["✓", "!"]);
});
