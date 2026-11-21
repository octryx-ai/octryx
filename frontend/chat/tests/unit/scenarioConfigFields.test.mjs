// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The server refuses scenario profile prompt matchers and tool fields (HTTP 422,
// `field_unsupported`); the admin panel never holds them in its defaults and never
// sends them.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_SCENARIO_EXECUTION_CONFIG,
  DEFAULT_SCENARIO_MATCH_CONFIG,
  DEFAULT_SCENARIO_PLANNER_CONFIG,
  UNSUPPORTED_SCENARIO_FIELDS,
  withoutUnsupportedScenarioFields,
} from "../../src/admin/config/scenarioConfigFields.ts";

test("the scenario defaults carry no unsupported field", () => {
  const defaults = {
    match_config: JSON.parse(DEFAULT_SCENARIO_MATCH_CONFIG),
    planner_config: JSON.parse(DEFAULT_SCENARIO_PLANNER_CONFIG),
    execution_config: JSON.parse(DEFAULT_SCENARIO_EXECUTION_CONFIG),
  };
  for (const [name, keys] of Object.entries(UNSUPPORTED_SCENARIO_FIELDS)) {
    for (const key of keys) assert.ok(!(key in defaults[name]), `${name}.${key}`);
  }
});

test("a stored unsupported field is never written back", () => {
  assert.deepEqual(
    withoutUnsupportedScenarioFields("match_config", { route_reasons: ["r"], keywords: [], message_patterns: ["x"] }),
    { route_reasons: ["r"] },
  );
  assert.deepEqual(
    withoutUnsupportedScenarioFields("planner_config", { token_budget: 900, tool_allowlist: ["bash"] }),
    { token_budget: 900 },
  );
  assert.deepEqual(withoutUnsupportedScenarioFields("execution_config", { blocked_tools: [] }), {});
});
