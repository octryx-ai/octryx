// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityRuns.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_AREA_CONFIGS, listAdminAreaTabRefs } from "../../src/admin/config/adminPanelAreas.ts";
import { outcomeLabel, outcomeTone, runsQuery, sessionLink, toolsLabel } from "../../src/admin/components/observability/runsModel.ts";

test("Runs is the Observability home for runs", () => {
  const refs = listAdminAreaTabRefs("operations");
  assert.ok(refs.some((ref) => ref.id === "observabilityRuns" && !ref.hidden));
  assert.equal(refs.find((ref) => ref.id === "observability"), undefined);
  assert.ok(ADMIN_AREA_CONFIGS.operations.groups.every((group) => group.label !== "Insights"));
});

test("outcomes are labelled with words and a tone, never colour alone", () => {
  assert.equal(outcomeLabel("needs_approval"), "needs approval");
  assert.equal(outcomeTone("blocked"), "danger");
  assert.equal(outcomeTone("needs_clarification"), "attention");
  assert.equal(outcomeTone(null), "neutral");
});

test("tool counts distinguish 'not recorded' from zero", () => {
  assert.equal(toolsLabel({ tool_count: null, tool_failed: null }), "–");
  assert.equal(toolsLabel({ tool_count: 0, tool_failed: 0 }), "0");
  assert.equal(toolsLabel({ tool_count: 7, tool_failed: 1 }), "7 / 1 failed");
});

test("the runs query sends only the filters that are set, bounded by the window", () => {
  const url = new URL(runsQuery({ windowHours: 24, workspaceId: "", source: "gateway", outcome: "", query: "  ", page: 2 }), "http://x");
  assert.equal(url.pathname, "/api/v1/observability/runs");
  assert.deepEqual(Object.fromEntries(url.searchParams), { window_hours: "24", page: "2", source: "gateway" });
});

test("only the owner of a run gets the chat link; chat state is owner-only", () => {
  assert.equal(sessionLink({ session_id: "s 1", viewer_is_owner: true }), "/chat?session_id=s%201");
  assert.equal(sessionLink({ session_id: "s1", viewer_is_owner: false }), null);
  assert.equal(sessionLink(null), null);
});
