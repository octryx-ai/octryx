import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDefaultToolSets } from "../../src/admin/components/defaultToolSets.ts";
import {
  familiesToText,
  labelledToText,
  parsePolicyListRefusal,
  parsePolicyLists,
  textToFamilies,
  textToLabelled,
  textToNames,
} from "../../src/admin/components/policyLists.ts";

test("an edited default set shows its version, its seed and its history", () => {
  const [set] = parseDefaultToolSets({
    source: "admin_policy_list",
    override: "supported",
    sets: [
      {
        capability_type: "diagnosis",
        key: "diagnosis.v2",
        version: 2,
        seed_key: "diagnosis.v1",
        origin: "admin",
        matches_seed: false,
        families: [{ name: "workflow_selection", tools: ["select_workflow"] }],
        history: [{ key: "diagnosis.v2", action: "policy_list.updated", at: "2026-10-01" }, { key: 3 }],
      },
    ],
  }).sets;

  assert.equal(set.version, 2);
  assert.equal(set.seedKey, "diagnosis.v1");
  assert.equal(set.matchesSeed, false);
  assert.deepEqual(set.history.map((entry) => entry.key), ["diagnosis.v2"]);
});

test("the text editors round-trip families and labelled entries in declared order", () => {
  const families = [
    { name: "workflow_selection", tools: ["select_workflow", "start_workflow"] },
    { name: "web", tools: ["web_search"] },
  ];
  assert.deepEqual(textToFamilies(familiesToText(families)), families);
  assert.deepEqual(textToFamilies("web:\n\n"), [{ name: "web", tools: [] }]);
  const options = [{ type: "c4_context", label: "C4: system context" }];
  assert.deepEqual(textToLabelled(labelledToText(options, "type"), "type"), options);
  assert.deepEqual(textToNames(" haiku \n\nnova-lite\n"), ["haiku", "nova-lite"]);
});

test("only closed refusal codes are read; lists without identity are dropped", () => {
  assert.deepEqual(
    parsePolicyListRefusal({ detail: { code: "unknown_tool", values: ["x", 1], message: "m" } }),
    { code: "unknown_tool", values: ["x"], message: "m" },
  );
  assert.equal(parsePolicyListRefusal({ detail: { code: "made_up" } }), null);
  assert.equal(parsePolicyListRefusal({ detail: "Admin role required" }), null);
  const lists = parsePolicyLists({
    lists: [
      { list_id: "model_capabilities", key: "model_capabilities.v1", version: 1, pinned: ["coding"], values: [] },
      { list_id: "broken" },
    ],
  });
  assert.deepEqual(lists.map((list) => list.listId), ["model_capabilities"]);
  assert.deepEqual(lists[0].pinned, ["coding"]);
});
