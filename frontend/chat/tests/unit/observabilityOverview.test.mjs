// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityOverview.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_AREA_CONFIGS, isAdminTabRefVisible, listAdminAreaTabRefs } from "../../src/admin/config/adminPanelAreas.ts";
import { attentionBreakdown, decisionsBreakdown } from "../../src/admin/components/observability/overviewModel.ts";

test("Observability opens on Overview; the navigation is Overview · Operate · Govern · Cost", () => {
  const config = ADMIN_AREA_CONFIGS.operations;
  assert.equal(config.defaultTab, "observabilityOverview");
  assert.deepEqual(config.groups.filter((group) => group.tabs.some((ref) => !ref.hidden)).map((group) => group.label),
    ["", "Operate", "Govern", "Cost"]);
  assert.deepEqual(listAdminAreaTabRefs("operations").filter((ref) => !ref.hidden).map((ref) => ref.id), [
    // Operations › Live leads the Operate group.
    "observabilityOverview", "operationsLive", "operationsCosts", "observabilityHealth", "observabilityRuns", "observabilityDecisions", "observabilityAudit", "usage",
  ]);
});

test("Costs shows only to platform admins and admins of the active Workspace; Live to everyone", () => {
  const ids = (isAdmin, canAdminWorkspace) => listAdminAreaTabRefs("operations")
    .filter((ref) => isAdminTabRefVisible(ref, isAdmin, {}, canAdminWorkspace)).map((ref) => ref.id);
  assert.ok(!ids(false, false).includes("operationsCosts") && ids(false, false).includes("operationsLive"));
  assert.ok(ids(false, true).includes("operationsCosts"), "a Workspace admin");
  assert.ok(ids(true, true).includes("operationsCosts"), "a platform admin");
});

test("the attention and decision tiles say what they count", () => {
  const item = (label) => ({ label });
  assert.equal(attentionBreakdown([item("✕ failing"), item("✕ failing"), item("! waiting"), item("! cost")]),
    "2 failing · 1 waiting · 1 cost");
  assert.equal(attentionBreakdown([]), "nothing needs attention");
  assert.equal(decisionsBreakdown({ denied: 14, approved: 6, needs_approval: 2 }), "14 denied · 2 needs approval · 6 approved");
  assert.equal(decisionsBreakdown({}), "no decisions recorded today");
});
