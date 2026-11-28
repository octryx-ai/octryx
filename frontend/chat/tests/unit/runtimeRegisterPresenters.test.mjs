// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/runtimeRegisterPresenters.test.mjs
//
// Presentation contracts of the Runtime registers. Each helper
// only labels or explains stored state; none may change a stored value.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { executionModeSummary } from "../../src/admin/components/runtimeTab/executionModeSummary.ts";
import { researchProfileSummary } from "../../src/admin/components/researchPolicies/researchProfileSummary.ts";
import { mcpCatalogRequirements } from "../../src/admin/components/mcpCatalogSummary.ts";

describe("effective execution mode (49c)", () => {
  test("host, docker with and without host fallback", () => {
    assert.equal(executionModeSummary({ execution_runtime_provider: "host" }).target, "Host");
    const strict = executionModeSummary({ execution_runtime_provider: "docker" });
    assert.equal(strict.target, "Docker");
    assert.match(strict.detail, /fails instead of running on the host/);
    const fallback = executionModeSummary({
      execution_runtime_provider: "docker",
      execution_runtime_allow_host_fallback: true,
    });
    assert.match(fallback.detail, /run on the host instead/);
  });

  test("hard sandbox mode never falls back", () => {
    const hard = executionModeSummary({
      execution_runtime_provider: "docker",
      execution_runtime_allow_host_fallback: true,
      execution_runtime_sandbox_mode: "hard",
    });
    assert.match(hard.detail, /fails instead of running on the host/);
  });
});

describe("row summaries (52, 53, 50a)", () => {
  test("research profiles show their limits from the spec only", () => {
    assert.equal(
      researchProfileSummary({
        research_strategy: { min_source_count: 8, target_source_count: 12, max_source_count: 20, max_search_rounds: 4 },
        delegation_policy: { max_child_agents: 0 },
        output_policy: { target_pages: { target: 10 } },
      }),
      "8–20 sources (target 12) · up to 4 search rounds · no child agents · about 10 pages",
    );
    assert.equal(researchProfileSummary({}), "No limits in the spec");
  });

  test("MCP catalog rows name required settings and secret references", () => {
    assert.equal(mcpCatalogRequirements({ fields: [] }), "No configuration");
    assert.equal(
      mcpCatalogRequirements({
        fields: [
          { name: "api_key", label: "API key", type: "password", required: true },
          { name: "region", label: "Region", type: "text" },
        ],
      }),
      "API key (secret reference) · 1 optional setting",
    );
  });
});
