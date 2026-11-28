// Runtime audit R-bug + P-7: each Runtime page saves only its own fields, the shared save
// never writes the artifact store, and a Workspace cost cap can go back to "inherit".
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { buildRuntimeSettingsPayload } from "../../src/admin/hooks/useAdminRuntimeManagementActions.helpers.ts";
import {
  MISSING_OVERRIDE_ERROR,
  REQUEST_COST_CAP,
  SESSION_COST_CAP,
  buildWorkspaceCostCapsPayload,
  costCapInheritFromScope,
} from "../../src/admin/components/runtimeTab/workspaceCostCapsSave.ts";

// Every draft a Runtime page can hold, filled, so a leak into another page's payload shows up.
const ARGS = {
  runtimeGlobalOutputDraft: "4096",
  runtimeDefaultModelDraft: "model-a",
  runtimeAuthOidcOnlyDraft: true,
  runtimeExecutionProviderDraft: "docker",
  runtimeExecutionDockerImageDraft: " python:3.12 ",
  runtimeExecutionDockerNetworkDraft: "none",
  runtimeExecutionAllowHostFallback: false,
  runtimeWorkspaceBaseDirDraft: "/srv/ws",
  runtimeWorkspaceMaxAgeDraft: "24",
  runtimeWorkspaceStorageBackendDraft: "s3",
  runtimeWorkspaceStorageBucketDraft: "bucket",
  runtimeWorkspaceStoragePrefixDraft: "prefix",
  runtimeWorkspaceSyncExcludedDirsDraft: "node_modules",
  runtimeWorkspaceSyncExcludedGlobsDraft: "*.log",
  runtimeWorkspaceSyncMaxFileSizeDraft: "1000",
  runtimeWorkspaceSyncMaxFileCountDraft: "10",
  runtimeOfficeTemplatesDraft: [{ key: "k", name: "n", doc_type: "docx", path: "p", description: "" }],
  sanitizeOfficeTemplateKey: (key) => key,
  runtimeLlmSecurityTimeoutDraft: "8",
  runtimeLlmSecurityReviewThresholdDraft: "40",
  runtimeLlmSecurityDenyThresholdDraft: "80",
  runtimeSecurityAnalyzerChainDraft: "rules, llm",
  runtimeApproxCharsDraft: "4",
  runtimeTraceMaxStringDraft: "16000",
  runtimeTraceMaxListDraft: "200",
  runtimeTraceMaxDictDraft: "120",
  runtimeScriptOutputDraft: "8000",
  runtimeRequestTimeoutDraft: "90",
  runtimeSessionCostLimitDraft: "5",
  runtimeRequestCostLimitDraft: "",
  artifactStoreBackend: "s3",
};

const SECTIONS = ["execution", "security", "limits"];
// Owned by their own narrow saves (model defaults, sign-in, artifact store, office templates).
const NEVER_SENT = [
  "agent_default_model",
  "auth_oidc_only",
  "max_output_tokens_default",
  "office_template_library",
  "artifact_store_backend",
  "artifact_store_bucket",
  "artifact_store_prefix",
  "artifact_store_s3_region",
  "artifact_store_s3_endpoint_url",
];

describe("each Runtime page saves only its own fields", () => {
  test("no key is sent by two pages, and no page sends another owner's key", () => {
    const seen = new Map();
    for (const section of SECTIONS) {
      for (const key of Object.keys(buildRuntimeSettingsPayload(ARGS, section))) {
        assert.equal(seen.has(key), false, `${key} sent by ${seen.get(key)} and ${section}`);
        seen.set(key, section);
        assert.equal(NEVER_SENT.includes(key), false, `${section} sends ${key}`);
      }
    }
  });

  test("a page sends exactly what it renders", () => {
    assert.deepEqual(buildRuntimeSettingsPayload(ARGS, "security").security_analyzer_chain, ["rules", "llm"]);
    assert.equal(buildRuntimeSettingsPayload(ARGS, "execution").execution_runtime_docker_image, "python:3.12");
  });

  test("the platform cost caps keep their documented semantics (empty = 0 = no cap)", () => {
    const limits = buildRuntimeSettingsPayload(ARGS, "limits");
    assert.equal(limits.agent_session_cost_limit_usd, 5);
    assert.equal(limits.agent_request_cost_limit_usd, 0);
  });
});

describe("workspace cost caps", () => {
  test("an inherited cap is listed, an override is a number, 0 stays an explicit no-cap", () => {
    const built = buildWorkspaceCostCapsPayload(
      { [SESSION_COST_CAP]: "0", [REQUEST_COST_CAP]: "2.5" },
      { [SESSION_COST_CAP]: false, [REQUEST_COST_CAP]: true },
    );
    assert.deepEqual(built, {
      payload: { [SESSION_COST_CAP]: 0, inherit_cost_limits: [REQUEST_COST_CAP] },
    });
  });

  test("an empty override is refused instead of becoming 0", () => {
    const built = buildWorkspaceCostCapsPayload(
      { [SESSION_COST_CAP]: " ", [REQUEST_COST_CAP]: "1" },
      { [SESSION_COST_CAP]: false, [REQUEST_COST_CAP]: false },
    );
    assert.deepEqual(built, { error: MISSING_OVERRIDE_ERROR, cap: SESSION_COST_CAP });
  });

  test("the inherit state follows the stored overrides", () => {
    assert.deepEqual(costCapInheritFromScope({ session_source: "project", request_source: "global" }), {
      [SESSION_COST_CAP]: false,
      [REQUEST_COST_CAP]: true,
    });
    assert.deepEqual(costCapInheritFromScope(undefined), {
      [SESSION_COST_CAP]: true,
      [REQUEST_COST_CAP]: true,
    });
  });
});
