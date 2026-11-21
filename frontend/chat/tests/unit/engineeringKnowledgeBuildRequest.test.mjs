// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The admin pack builder sends structured version coordinates; the backend
// never parses a prompt for pack-build versions.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS,
  engineeringKnowledgeBuildPayload,
  hasEngineeringKnowledgeTargetVersion,
} from "../../src/admin/components/engineeringKnowledgeBuildRequest.ts";

test("the builder payload carries only filled, trimmed coordinates", () => {
  assert.deepEqual(engineeringKnowledgeBuildPayload(DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS), {
    source_versions: { java: "21", spring_boot: "3.4" },
    target_versions: { java: "25", spring_boot: "4.0.3" },
  });
  const pythonOnly = {
    java: { source: "", target: "" },
    spring_boot: { source: " ", target: "" },
    python: { source: " 3.11 ", target: "3.12" },
  };
  assert.deepEqual(engineeringKnowledgeBuildPayload(pythonOnly), {
    source_versions: { python: "3.11" },
    target_versions: { python: "3.12" },
  });
});

test("a build needs at least one target version", () => {
  const empty = {
    java: { source: "21", target: "" },
    spring_boot: { source: "", target: "" },
    python: { source: "", target: "" },
  };
  assert.equal(hasEngineeringKnowledgeTargetVersion(empty), false);
  assert.equal(hasEngineeringKnowledgeTargetVersion(DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS), true);
});
