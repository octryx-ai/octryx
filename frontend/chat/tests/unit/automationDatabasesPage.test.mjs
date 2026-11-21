// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/automationDatabasesPage.test.mjs
//
// Databases is its own Automation page; a database states a real check or what is missing, never a
// constant "Connected"; recent queries read in words, including a cut answer. The databases and the
// recent queries are tables; the State column carries the first words of the status, the whole line as its reason.
import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_AREA_CONFIGS, listAdminAreaTabRefs } from "../../src/admin/config/adminPanelAreas.ts";
import {
  databaseIconKind,
  databaseNeedsAttention,
  databaseState,
  databaseStatus,
  queryBy,
  queryLine,
  queryResult,
} from "../../src/admin/components/databases/databasePresenters.ts";
import { ADMIN_ENTRIES } from "../../src/admin/config/adminEntries.ts";

test("Databases is a view of Connections next to Connectors", () => {
  const entry = ADMIN_ENTRIES.find((item) => item.label === "Connections");
  const pages = entry.views.flatMap((view) => (view.pages ?? []).map((page) => page.tab));
  // "connectors" has no segment: it is an alias page of Connections.
  assert.deepEqual(pages, ["adminConnections", "mcp", "restApis", "restApiCalls", "databases", "channels", "webhooks", "schedulers", "tasks"]);
});

test("a card says what is wrong or when it was checked", () => {
  const base = { id: "d1", name: "Reporting", db_type: "postgresql", is_active: true, tool_count: 2 };
  assert.equal(databaseStatus({ ...base, health: null }).text, "Not checked yet");
  assert.deepEqual(databaseStatus({ ...base, health: { status: "error", error: "Host not reachable" } }),
    { text: "Failing · Host not reachable", tone: "error" });
  assert.equal(databaseStatus({ ...base, tool_count: 0 }).text, "Needs a query tool · agents can't use it yet");
  assert.equal(databaseStatus({ ...base, is_active: false }).text, "Paused");
  assert.equal(databaseNeedsAttention({ ...base, tool_count: 0 }), true);
  assert.equal(databaseIconKind("postgres"), "postgresql");
  assert.equal(databaseIconKind("oracle"), "database");
});

test("recent queries read in words", () => {
  const query = { id: "q", tool: "Open items", database: "Reporting", status: "succeeded", failure_category: "",
    rows: 500, limit_reached: true, who: "agent-user", workspace: "Ops", started_at: null };
  assert.equal(queryLine(query), "by agent-user in Ops · 500 rows (limit reached, answer cut)");
  assert.equal(queryLine({ ...query, status: "failed", failure_category: "host_unreachable" }),
    "by agent-user in Ops · failed (host unreachable)");
});

test("the State column: short label, tone by meaning, the whole status as its reason", () => {
  const base = { id: "d1", name: "Reporting", db_type: "postgresql", is_active: true, tool_count: 2 };
  assert.deepEqual(databaseState({ ...base, health: { status: "error", error: "Host not reachable" } }),
    { label: "Failing", tone: "problem", title: "Failing · Host not reachable" });
  assert.deepEqual(databaseState({ ...base, tool_count: 0 }),
    { label: "Needs a query tool", tone: "attention", title: "Needs a query tool · agents can't use it yet" });
  assert.deepEqual(databaseState({ ...base, is_active: false }), { label: "Paused", tone: "neutral", title: "" });
  assert.deepEqual(databaseState({ ...base, health: null }), { label: "Not checked yet", tone: "neutral", title: "" });
});

test("a recent query's By and Result cells", () => {
  const query = { id: "q", tool: "Open items", database: "Reporting", status: "succeeded", failure_category: "",
    rows: 1, limit_reached: false, who: "agent-user", workspace: "Ops", started_at: null };
  assert.equal(queryBy(query), "agent-user in Ops");
  assert.equal(queryBy({ ...query, who: "", workspace: "" }), "");
  assert.deepEqual(queryResult(query), { failed: false, text: "1 row" });
  assert.deepEqual(queryResult({ ...query, rows: 500, limit_reached: true }),
    { failed: false, text: "500 rows (limit reached, answer cut)" });
  assert.deepEqual(queryResult({ ...query, status: "failed", failure_category: "host_unreachable" }),
    { failed: true, text: "host unreachable" });
});
