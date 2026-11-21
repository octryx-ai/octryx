import assert from "node:assert/strict";
import { test } from "node:test";
import {
  filterTools,
  inferToolSource,
  toolAvailability,
  toolSourceLabel,
} from "../../src/admin/components/toolCatalog/toolCatalogModel.ts";

function tool(name, extra = {}) {
  return { name, description: "", default_connector: null, connectors: [], is_core: false, change_only: false, plan_excluded: false, plan_only: false, ...extra };
}

test("tool sources are read from the registered name and connector", () => {
  assert.equal(inferToolSource(tool("mcp__github__search")), "mcp");
  assert.equal(inferToolSource(tool("database_tool_orders")), "database");
  assert.equal(toolSourceLabel(tool("connector_jira_search", { connectors: ["jira", "system"] })), "jira");
  assert.equal(toolSourceLabel(tool("knowledge_search", { default_connector: "system" })), "Built-in");
});

test("availability names core, discoverable and mode limits in words", () => {
  assert.deepEqual(toolAvailability(tool("a", { is_core: true })), { label: "Core", tone: "core" });
  assert.deepEqual(toolAvailability(tool("b", { change_only: true })), {
    label: "Discoverable · change modes only",
    tone: "change",
  });
});

test("source and availability filters combine", () => {
  const tools = [tool("a", { is_core: true }), tool("connector_x"), tool("c", { change_only: true })];
  assert.deepEqual(filterTools(tools, "core", "all").map((t) => t.name), ["a"]);
  assert.deepEqual(filterTools(tools, "connector", "all").map((t) => t.name), ["connector_x"]);
  assert.deepEqual(filterTools(tools, "all", "change_only").map((t) => t.name), ["c"]);
  assert.equal(filterTools(tools, "all", "all").length, 3);
});
