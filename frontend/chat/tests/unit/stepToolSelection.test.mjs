// Guided step form: tool picker and `tool_use` rules (judge follow-up).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  filterToolCatalog,
  normalizeToolCatalog,
  parseToolList,
  removeTool,
  serializeToolList,
  splitByCatalog,
  stepConfigIssue,
  stepConfigNeedsAttention,
  toggleTool,
  toolUseState,
  writeToolUse,
} from "../../src/admin/components/agentsTab/stepToolSelection.ts";

test("the tool list round-trips through the comma-separated contract, trimmed and deduplicated", () => {
  assert.deepEqual(parseToolList(" a ,b,, a,c "), ["a", "b", "c"]);
  assert.equal(serializeToolList(parseToolList("a, b, c")), "a, b, c");
  assert.deepEqual(parseToolList(""), []);
  assert.deepEqual(normalizeToolCatalog(["x", " x", 3, null, "y"]), ["x", "y"]);
  assert.deepEqual(normalizeToolCatalog(undefined), []);
});

test("saved IDs outside the catalog stay selected and are only removed explicitly", () => {
  const catalog = ["knowledge_search", "get_confluence_page"];
  const saved = "knowledge_search, retired_tool";
  assert.deepEqual(splitByCatalog(parseToolList(saved), catalog), { known: ["knowledge_search"], unknown: ["retired_tool"] });
  assert.equal(toggleTool(saved, "get_confluence_page", true), "knowledge_search, retired_tool, get_confluence_page");
  assert.equal(toggleTool(saved, "knowledge_search", false), "retired_tool");
  assert.equal(removeTool(saved, "retired_tool"), "knowledge_search");
});

test("picking never expands the selection beyond the picked tool", () => {
  assert.equal(toggleTool("", "a", true), "a");
  assert.equal(toggleTool("a", "a", true), "a");
  assert.equal(toggleTool("a", "  ", true), "a");
  assert.deepEqual(filterToolCatalog(["Knowledge_Search", "jira_get"], "KNOW"), ["Knowledge_Search"]);
  assert.deepEqual(filterToolCatalog(["a", "b"], " "), ["a", "b"]);
});

test("the configuration disclosure opens for existing or broken configuration only", () => {
  assert.equal(stepConfigNeedsAttention("{\n  \n}"), false);
  assert.equal(stepConfigNeedsAttention(""), false);
  assert.equal(stepConfigNeedsAttention('{"tool_use":"optional"}'), false);
  assert.equal(stepConfigNeedsAttention('{"tdd_cycle_phases":["write_tests"]}'), true);
  assert.equal(stepConfigNeedsAttention("{ broken"), true);
  assert.equal(stepConfigIssue("{ broken"), "Step configuration must be valid JSON.");
  assert.equal(stepConfigIssue(""), null);
});

test("tool use shows the default until the user changes it, then keeps every other key", () => {
  assert.deepEqual(toolUseState("{}", "a"), { value: "required", source: "default", writable: true });
  assert.deepEqual(toolUseState("{}", ""), { value: "optional", source: "default", writable: true });
  assert.deepEqual(toolUseState('{"tool_use":"optional"}', "a"), { value: "optional", source: "explicit", writable: true });
  assert.deepEqual(toolUseState('{"tool_use":" Optional "}', "a"), { value: "optional", source: "explicit", writable: true });
  assert.deepEqual(toolUseState('{"tool_use":null}', ""), { value: "optional", source: "default", writable: true });
  // An unrecognised value fails closed to required, as the runtime guard does.
  assert.deepEqual(toolUseState('{"tool_use":"always"}', ""), { value: "required", source: "unrecognized", writable: true });
  assert.equal(toolUseState("{ broken", "a").writable, false);
  const written = JSON.parse(writeToolUse('{"tdd_cycle_phases":["write_tests"],"custom":{"x":1}}', "optional"));
  assert.deepEqual(written, { tdd_cycle_phases: ["write_tests"], custom: { x: 1 }, tool_use: "optional" });
  assert.equal(writeToolUse("{ broken", "required"), null);
  assert.equal(writeToolUse("[1]", "required"), null);
});
