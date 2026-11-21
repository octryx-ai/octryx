// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/runtimeRegisterPresenters.test.mjs
//
// Presentation contracts of the Runtime registers. Each helper
// only labels or explains stored state; none may change a stored value.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { providerAuthLabel } from "../../src/admin/components/providerTab/providerAuthLabel.ts";
import { executionModeSummary } from "../../src/admin/components/runtimeTab/executionModeSummary.ts";
import {
  REDUCTION_MEANING,
  filterCompressionLogs,
  filterCompressors,
} from "../../src/admin/components/runtimeTab/compressionModel.ts";
import { researchProfileSummary } from "../../src/admin/components/researchPolicies/researchProfileSummary.ts";
import { mcpCatalogRequirements } from "../../src/admin/components/mcpCatalogSummary.ts";

describe("provider credential label (48)", () => {
  test("Bedrock without static keys uses AWS IAM, never 'No key'", () => {
    assert.equal(providerAuthLabel({ driver: "bedrock_api", has_api_key: false }), "AWS IAM / profile");
    assert.equal(
      providerAuthLabel({ driver: "bedrock_api", auth_mode: "aws_credentials", aws_static_credentials_configured: true }),
      "AWS access keys configured",
    );
    assert.equal(
      providerAuthLabel({ driver: "bedrock_api", auth_mode: "aws_credentials", aws_static_credentials_configured: false }),
      "AWS access keys missing",
    );
  });

  test("other providers keep the key state", () => {
    assert.equal(providerAuthLabel({ driver: "openrouter_api", has_api_key: false }), "No key");
    assert.equal(providerAuthLabel({ driver: "openrouter_api", has_api_key: true }), "Key configured");
    assert.equal(providerAuthLabel({ runtime_kind: "local", endpoint_url: "http://ollama:11434" }), "local runtime");
  });
});

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

describe("compression filter (49h)", () => {
  const items = [
    { id: "1", tool_name: "get_jira_ticket", strategy: "jira_extract_fields", is_active: true },
    { id: "2", tool_name: "loki_query", strategy: "loki_tail_errors", is_active: false },
  ];

  test("search matches tool, profile key or label; status uses the draft", () => {
    assert.deepEqual(filterCompressors(items, {}, "jira", "all").map((i) => i.id), ["1"]);
    assert.deepEqual(filterCompressors(items, {}, "tail errors", "all").map((i) => i.id), ["2"]);
    assert.deepEqual(filterCompressors(items, {}, "", "off").map((i) => i.id), ["2"]);
    const drafts = { loki_query: { strategy: "loki_tail_errors", config: {}, is_active: true } };
    assert.deepEqual(filterCompressors(items, drafts, "", "on").map((i) => i.id), ["1", "2"]);
  });

  test("the log follows the same search and 0 % is explained", () => {
    const logs = [{ id: "a", tool_name: "loki_query", strategy: "loki_tail_errors" }];
    assert.equal(filterCompressionLogs(logs, "jira").length, 0);
    assert.match(REDUCTION_MEANING, /0 % means nothing was removed/);
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
