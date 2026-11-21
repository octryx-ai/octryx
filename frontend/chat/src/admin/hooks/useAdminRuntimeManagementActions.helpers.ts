import type { AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";
import type { RuntimeSettingsActionArgs } from "./useAdminRuntimeManagementActions.types";

// The Runtime pages that share the runtime-settings PUT. Each page saves only the
// keys it renders: the backend treats an absent key as unchanged, so one page can
// never overwrite another page's values. Model defaults, sign-in and the artifact
// store have their own narrow saves and are not listed here.
export type RuntimeSettingsSection =
  | "execution"
  | "security"
  | "limits";

const optionalNumber = (value: string) => (value ? Number(value) : null);

function executionPayload(args: RuntimeSettingsActionArgs) {
  return {
    execution_runtime_provider: args.runtimeExecutionProviderDraft,
    execution_runtime_docker_image: args.runtimeExecutionDockerImageDraft.trim(),
    execution_runtime_docker_network_mode: args.runtimeExecutionDockerNetworkDraft,
    execution_runtime_allow_host_fallback: args.runtimeExecutionAllowHostFallback,
    session_workspace_base_dir: args.runtimeWorkspaceBaseDirDraft.trim(),
    session_workspace_max_age_hours: optionalNumber(args.runtimeWorkspaceMaxAgeDraft),
    session_workspace_storage_backend: args.runtimeWorkspaceStorageBackendDraft,
    session_workspace_storage_bucket: args.runtimeWorkspaceStorageBucketDraft.trim(),
    session_workspace_storage_prefix: args.runtimeWorkspaceStoragePrefixDraft.trim(),
    session_workspace_sync_excluded_dirs:
      args.runtimeWorkspaceSyncExcludedDirsDraft.trim(),
    session_workspace_sync_excluded_globs:
      args.runtimeWorkspaceSyncExcludedGlobsDraft.trim(),
    session_workspace_sync_max_file_size_bytes:
      args.runtimeWorkspaceSyncMaxFileSizeDraft
        ? Number(args.runtimeWorkspaceSyncMaxFileSizeDraft)
        : 0,
    session_workspace_sync_max_file_count: args.runtimeWorkspaceSyncMaxFileCountDraft
      ? Number(args.runtimeWorkspaceSyncMaxFileCountDraft)
      : 5000,
  };
}

function securityPayload(args: RuntimeSettingsActionArgs) {
  return {
    llm_security_analyzer_timeout_seconds: optionalNumber(args.runtimeLlmSecurityTimeoutDraft),
    llm_security_analyzer_review_threshold: optionalNumber(
      args.runtimeLlmSecurityReviewThresholdDraft,
    ),
    llm_security_analyzer_deny_threshold: optionalNumber(
      args.runtimeLlmSecurityDenyThresholdDraft,
    ),
    security_analyzer_chain: args.runtimeSecurityAnalyzerChainDraft
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  };
}

// Platform-level cost caps keep their documented semantics: 0 turns a cap off,
// and an empty platform field saves 0. Workspace overrides use their own save
// with an explicit "inherit" state (workspaceCostCapsSave.ts).
function limitsPayload(args: RuntimeSettingsActionArgs) {
  return {
    approx_chars_per_token: optionalNumber(args.runtimeApproxCharsDraft),
    trace_max_string: optionalNumber(args.runtimeTraceMaxStringDraft),
    trace_max_list_items: optionalNumber(args.runtimeTraceMaxListDraft),
    trace_max_dict_items: optionalNumber(args.runtimeTraceMaxDictDraft),
    saved_script_max_output_chars: optionalNumber(args.runtimeScriptOutputDraft),
    runtime_request_timeout_seconds: optionalNumber(args.runtimeRequestTimeoutDraft),
    agent_session_cost_limit_usd: args.runtimeSessionCostLimitDraft
      ? Number(args.runtimeSessionCostLimitDraft)
      : 0,
    agent_request_cost_limit_usd: args.runtimeRequestCostLimitDraft
      ? Number(args.runtimeRequestCostLimitDraft)
      : 0,
    llm_cache_ttl_seconds: optionalNumber(args.runtimeCacheTtlDraft),
    llm_cache_tools_ttl_seconds: optionalNumber(args.runtimeToolsCacheTtlDraft),
    llm_tool_planner_trace_call_enabled: args.runtimeToolPlannerTraceCallEnabled,
    llm_tool_planner_max_tokens: args.runtimeToolPlannerMaxTokensDraft
      ? Number(args.runtimeToolPlannerMaxTokensDraft)
      : 900,
    llm_tool_planner_timeout_seconds: args.runtimeToolPlannerTimeoutDraft
      ? Number(args.runtimeToolPlannerTimeoutDraft)
      : 30,
  };
}

const SECTION_PAYLOADS: Record<
  RuntimeSettingsSection,
  (args: RuntimeSettingsActionArgs) => Record<string, unknown>
> = {
  execution: executionPayload,
  security: securityPayload,
  limits: limitsPayload,
};

export function buildRuntimeSettingsPayload(
  args: RuntimeSettingsActionArgs,
  section: RuntimeSettingsSection,
) {
  return SECTION_PAYLOADS[section](args);
}

// Settings, sign-in, default output and model, execution runtime, workspace and office templates.
function applyExecutionDrafts(
  updated: AdminRuntimeSettings,
  args: RuntimeSettingsActionArgs,
) {
  args.setRuntimeSettings(updated);
  args.setRuntimeAuthOidcOnlyDraft(Boolean(updated.auth_oidc_only));
  args.setRuntimeGlobalOutputDraft(
    updated.max_output_tokens_default != null
      ? String(updated.max_output_tokens_default)
      : "",
  );
  args.setRuntimeDefaultModelDraft(updated.agent_default_model || "");
  args.setRuntimeExecutionProviderDraft(
    updated.execution_runtime_provider || "host",
  );
  args.setRuntimeExecutionDockerImageDraft(
    updated.execution_runtime_docker_image || "python:3.11-slim",
  );
  args.setRuntimeExecutionDockerNetworkDraft(
    updated.execution_runtime_docker_network_mode || "none",
  );
  args.setRuntimeExecutionAllowHostFallback(
    Boolean(updated.execution_runtime_allow_host_fallback),
  );
  args.setRuntimeWorkspaceBaseDirDraft(updated.session_workspace_base_dir || "");
  args.setRuntimeWorkspaceMaxAgeDraft(
    String(updated.session_workspace_max_age_hours ?? 24),
  );
  args.setRuntimeWorkspaceStorageBackendDraft(
    updated.session_workspace_storage_backend || "disabled",
  );
  args.setRuntimeWorkspaceStorageBucketDraft(
    updated.session_workspace_storage_bucket || "",
  );
  args.setRuntimeWorkspaceStoragePrefixDraft(
    updated.session_workspace_storage_prefix || "",
  );
  args.setRuntimeWorkspaceSyncExcludedDirsDraft(
    updated.session_workspace_sync_excluded_dirs || "",
  );
  args.setRuntimeWorkspaceSyncExcludedGlobsDraft(
    updated.session_workspace_sync_excluded_globs || "",
  );
  args.setRuntimeWorkspaceSyncMaxFileSizeDraft(
    String(updated.session_workspace_sync_max_file_size_bytes ?? 0),
  );
  args.setRuntimeWorkspaceSyncMaxFileCountDraft(
    String(updated.session_workspace_sync_max_file_count ?? 5000),
  );
  args.setRuntimeOfficeTemplatesDraft(updated.office_template_library || []);
}

// Security analyzer, review models and completion token drafts.
function applySecurityDrafts(
  updated: AdminRuntimeSettings,
  args: RuntimeSettingsActionArgs,
) {
  args.setRuntimeLlmSecurityTimeoutDraft(
    String(updated.llm_security_analyzer_timeout_seconds ?? 8),
  );
  args.setRuntimeLlmSecurityReviewThresholdDraft(
    String(updated.llm_security_analyzer_review_threshold ?? 40),
  );
  args.setRuntimeLlmSecurityDenyThresholdDraft(
    String(updated.llm_security_analyzer_deny_threshold ?? 80),
  );
  args.setRuntimeSecurityAnalyzerChainDraft(
    (updated.security_analyzer_chain || []).join(", "),
  );
  args.setRuntimeDefaultCompletionDraft(
    String(updated.default_completion_tokens ?? 4096),
  );
  args.setRuntimeExtendedCompletionDraft(
    String(updated.extended_completion_tokens ?? 8192),
  );
}

// Trace, timeout, cost cap, cache and tool planner drafts.
function applyLimitsDrafts(
  updated: AdminRuntimeSettings,
  args: RuntimeSettingsActionArgs,
) {
  args.setRuntimeApproxCharsDraft(String(updated.approx_chars_per_token ?? 4));
  args.setRuntimeTraceMaxStringDraft(String(updated.trace_max_string ?? 16000));
  args.setRuntimeTraceMaxListDraft(String(updated.trace_max_list_items ?? 200));
  args.setRuntimeTraceMaxDictDraft(String(updated.trace_max_dict_items ?? 120));
  args.setRuntimeScriptOutputDraft(
    String(updated.saved_script_max_output_chars ?? 8000),
  );
  args.setRuntimeRequestTimeoutDraft(
    String(updated.runtime_request_timeout_seconds ?? 90),
  );
  args.setRuntimeSessionCostLimitDraft(
    String(updated.agent_session_cost_limit_usd ?? 5),
  );
  args.setRuntimeRequestCostLimitDraft(
    String(updated.agent_request_cost_limit_usd ?? 1.5),
  );
  args.setRuntimeCacheTtlDraft(String(updated.llm_cache_ttl_seconds ?? 300));
  args.setRuntimeToolsCacheTtlDraft(
    String(updated.llm_cache_tools_ttl_seconds ?? 120),
  );
  args.setRuntimeToolPlannerTraceCallEnabled(
    Boolean(updated.llm_tool_planner_trace_call_enabled),
  );
  args.setRuntimeToolPlannerMaxTokensDraft(
    String(updated.llm_tool_planner_max_tokens ?? 900),
  );
  args.setRuntimeToolPlannerTimeoutDraft(
    String(updated.llm_tool_planner_timeout_seconds ?? 30),
  );
}

export function applyRuntimeSettingsToDrafts(
  updated: AdminRuntimeSettings,
  args: RuntimeSettingsActionArgs,
) {
  applyExecutionDrafts(updated, args);
  applySecurityDrafts(updated, args);
  applyLimitsDrafts(updated, args);
}
