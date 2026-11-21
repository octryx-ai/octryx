// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityDecisions.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { listAdminAreaTabRefs, resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";
import {
  decisionRecordHref, decisionsQuery, decisionTone, EDIT_TARGETS, GATE_LABELS, policyDecisionsHref, readDecisionParams,
} from "../../src/admin/components/observability/decisionsModel.ts";
import { decisionHref } from "../../src/admin/components/policyEngine/policyEngineDecisions.ts";

test("Decisions lives in Observability → Govern; the Policies page has no decisions address", () => {
  assert.equal(resolveAdminAreaForTab("observabilityDecisions"), "operations");
  assert.equal(listAdminAreaTabRefs("admin").find((ref) => ref.id === "policyDecisions"), undefined);
});

test("every gate names where its rule is edited; Decisions edits nothing itself", () => {
  for (const gate of Object.keys(GATE_LABELS)) {
    assert.ok(EDIT_TARGETS[gate]?.label, `${gate} needs an edit target`);
    assert.ok(EDIT_TARGETS[gate].tab || EDIT_TARGETS[gate].href);
  }
});

test("refusal links and policy links open the timeline, old ids stay safe", () => {
  assert.equal(decisionHref("d-1"), decisionRecordHref("d-1"));
  assert.match(policyDecisionsHref("prod-read-only"), /tab=observabilityDecisions&policy=prod-read-only/);
  assert.deepEqual(readDecisionParams("?decision=d-1&policy=p-1"), { decision: "d-1", policy: "p-1", outcome: "" });
  assert.equal(readDecisionParams("?decision=<script>").decision, null);
});

test("outcomes carry a tone and the query sends only set filters", () => {
  assert.equal(decisionTone("denied"), "danger");
  assert.equal(decisionTone("needs_approval"), "attention");
  assert.equal(decisionTone("approved"), "active");
  assert.equal(decisionTone("remedied"), "running");
  const url = new URL(decisionsQuery({ windowHours: 168, outcome: "", gate: "mcp_access", workspaceId: "", policyId: "", page: 1 }), "http://x");
  assert.deepEqual(Object.fromEntries(url.searchParams), { window_hours: "168", page: "1", gate: "mcp_access" });
});
