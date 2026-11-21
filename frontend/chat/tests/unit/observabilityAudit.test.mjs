// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityAudit.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";
import { auditDiffLines, auditQuery } from "../../src/admin/components/observability/auditModel.ts";

test("the Audit log lives in Observability → Govern", () => {
  assert.equal(resolveAdminAreaForTab("observabilityAudit"), "operations");
});

test("a change shows only the fields that changed, removed before added", () => {
  const lines = auditDiffLines({ before: { cap: 5, name: "a" }, after: { cap: 8, name: "a" } });
  assert.deepEqual(lines, [{ kind: "del", text: "- cap: 5" }, { kind: "add", text: "+ cap: 8" }]);
  assert.deepEqual(auditDiffLines({ before: { a: 1 }, after: { a: 1 } }), [{ kind: "same", text: "  no field changed" }]);
  assert.deepEqual(auditDiffLines({ rows: 3 }), [{ kind: "same", text: "  rows: 3" }]);
});

test("the query sends only set filters", () => {
  assert.equal(auditQuery({ category: "", query: " ", page: 1, windowDays: 30 }), "window_days=30&page=1");
  assert.equal(auditQuery({ category: "Governance", query: "cap", page: 2, windowDays: 7 }),
    "window_days=7&page=2&category=Governance&q=cap");
});

test("a recorded event name reads as words, a request line stays as it is", async () => {
  const { auditChangeLabel, auditObjectParts } = await import("../../src/admin/components/observability/auditModel.ts");
  assert.equal(auditChangeLabel("policy_engine.policy_set_draft_saved"), "Policy set draft saved");
  assert.equal(auditChangeLabel("admin.project_config.updated"), "Project config updated");
  assert.equal(auditChangeLabel("flow_definition.saved"), "Flow definition saved");
  assert.equal(auditChangeLabel("flow_draft_saved"), "Flow draft saved");
  assert.equal(auditChangeLabel("login"), "login");
  assert.equal(auditChangeLabel("POST /api/v1/admin/policy-engine/test-bench/generate"), "POST /api/v1/admin/policy-engine/test-bench/generate");
  assert.deepEqual(auditObjectParts("policy_set_version · b5df4d67-3c8e-4272-95d4-4e9d513b3e0e"),
    { kind: "Policy set version", id: "b5df4d67", full: "policy_set_version · b5df4d67-3c8e-4272-95d4-4e9d513b3e0e" });
  assert.deepEqual(auditObjectParts("api"), { kind: "API", id: null, full: "api" });
  assert.equal(auditObjectParts(null), null);
});
