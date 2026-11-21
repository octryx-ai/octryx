import assert from "node:assert/strict";
import { test } from "node:test";
import { groupPromptItems, searchPromptItems, toolNameOf } from "../../src/admin/components/promptCatalog/promptCatalogSearch.ts";
import { isOverridden } from "../../src/admin/components/promptCatalog/promptCatalogModel.ts";

function item(key, area, extra = {}) {
  return { key, area, title: key, description: "", risk: "standard", placeholders: [], published: null, seed_digest: "", open_versions: 0, override_count: 0, ...extra };
}

test("tool keys group by tool with the description first, then the parameters", () => {
  const groups = groupPromptItems([
    item("tool.jira_search.param.query", "tool"),
    item("tool.github_pr.description", "tool"),
    item("tool.jira_search.description", "tool", { override_count: 2 }),
    item("tool.jira_search.param.limit", "tool", { open_versions: 1 }),
  ]);
  assert.deepEqual(
    groups.map((group) => [group.label, group.items.map((row) => row.key)]),
    [
      ["github_pr", ["tool.github_pr.description"]],
      ["jira_search", ["tool.jira_search.description", "tool.jira_search.param.limit", "tool.jira_search.param.query"]],
    ],
  );
  assert.equal(groups[1].overrides, 2);
  assert.equal(groups[1].openVersions, 1);
  assert.equal(toolNameOf("mcp.knowledge_search.description"), "knowledge_search");
});

test("prompt keys keep grouping by area", () => {
  const groups = groupPromptItems([item("system.z", "system"), item("evidence.a", "evidence"), item("system.a", "system")]);
  assert.deepEqual(groups.map((group) => [group.label, group.items.map((row) => row.key)]), [
    ["evidence", ["evidence.a"]],
    ["system", ["system.a", "system.z"]],
  ]);
});

test("search matches every term in key, title or description, case-insensitively", () => {
  const items = [
    item("tool.jira_search.description", "tool", { title: "jira_search: description" }),
    item("tool.jira_search.param.query", "tool", { description: "JQL query text" }),
    item("tool.github_pr.description", "tool"),
  ];
  assert.deepEqual(searchPromptItems(items, "JIRA query").map((row) => row.key), ["tool.jira_search.param.query"]);
  assert.equal(searchPromptItems(items, "  ").length, 3);
  assert.equal(searchPromptItems(items, "confluence").length, 0);
});

test("a key is overridden only when its published text is not the shipped one (A7)", () => {
  assert.equal(isOverridden(item("system.a", "system", { seed_digest: "d1" })), false);
  assert.equal(isOverridden(item("system.a", "system", { seed_digest: "d1", published: { source: "seed", digest: "d1" } })), false);
  assert.equal(isOverridden(item("system.a", "system", { seed_digest: "d1", published: { source: "admin", digest: "d2" } })), true);
  assert.equal(isOverridden(item("system.a", "system", { seed_digest: "d2", published: { source: "seed", digest: "d1" } })), true);
});
