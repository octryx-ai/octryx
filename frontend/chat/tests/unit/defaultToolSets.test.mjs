import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDefaultToolSets } from "../../src/admin/components/defaultToolSets.ts";

test("the governed default sets are parsed read-only, class by class", () => {
  const view = parseDefaultToolSets({
    source: "code_owned",
    override: "not_supported",
    sets: [
      {
        capability_type: "diagnosis",
        key: "diagnosis.v1",
        title: "Chat and diagnosis",
        description: "Read-only chat.",
        tool_count: 999,
        families: [
          { name: "workflow_selection", tools: ["select_workflow", "list_available_workflows"] },
          { name: "knowledge", tools: ["knowledge_search", "select_workflow"] },
        ],
        unregistered_tools: [],
      },
    ],
  });

  assert.equal(view.source, "code_owned");
  assert.equal(view.overrideSupported, false);
  assert.equal(view.sets.length, 1);
  assert.equal(view.sets[0].key, "diagnosis.v1");
  // The count is what the families hold (deduplicated), not the payload's claim.
  assert.equal(view.sets[0].toolCount, 3);
});

test("malformed sets and families are dropped instead of guessed", () => {
  const view = parseDefaultToolSets({
    sets: [
      { capability_type: "change" },
      { key: "plan.v1" },
      { capability_type: "admin", key: "admin.v1", families: [{ name: "x" }, "bad"], unregistered_tools: ["gone", 4] },
    ],
  });

  assert.deepEqual(
    view.sets.map((set) => set.key),
    ["admin.v1"],
  );
  assert.deepEqual(view.sets[0].families, []);
  assert.deepEqual(view.sets[0].unregisteredTools, ["gone"]);
  assert.equal(view.sets[0].title, "admin");
  assert.deepEqual(parseDefaultToolSets(null).sets, []);
});
