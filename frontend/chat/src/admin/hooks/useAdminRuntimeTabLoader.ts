import type { Dispatch, SetStateAction } from "react";
import type { AdminCorpIdentityListResponse, AdminOfficeTemplateEntry, AdminRuntime, AdminRuntimeSettings, AdminToolResultCompressor, AdminToolResultCompressionLog } from "../types/adminPanelTypes.runtimeCorp";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type LoadRuntimesTabDataArgs = {
  readJson: ReadJsonFn;
  providers: AdminProvider[];
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setRuntimeSettings: Dispatch<SetStateAction<AdminRuntimeSettings>>;
  setToolResultCompressors: Dispatch<
    SetStateAction<AdminToolResultCompressor[]>
  >;
  setToolResultCompressionLogs: Dispatch<
    SetStateAction<AdminToolResultCompressionLog[]>
  >;
  setToolResultCompressorDrafts: Dispatch<
    SetStateAction<
      Record<
        string,
        {
          strategy: string;
          config: Record<string, unknown>;
          is_active: boolean;
        }
      >
    >
  >;
  setRuntimeGlobalOutputDraft: Dispatch<SetStateAction<string>>;
  setRuntimeDefaultModelDraft: Dispatch<SetStateAction<string>>;
  setRuntimeAuthOidcOnlyDraft: Dispatch<SetStateAction<boolean>>;
  setRuntimeExecutionProviderDraft: Dispatch<SetStateAction<"host" | "docker">>;
  setRuntimeExecutionDockerImageDraft: Dispatch<SetStateAction<string>>;
  setRuntimeExecutionDockerNetworkDraft: Dispatch<
    SetStateAction<"none" | "bridge" | "host">
  >;
  setRuntimeExecutionAllowHostFallback: Dispatch<SetStateAction<boolean>>;
  setRuntimeWorkspaceBaseDirDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceMaxAgeDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceStorageBackendDraft: Dispatch<
    SetStateAction<AdminRuntimeSettings["session_workspace_storage_backend"]>
  >;
  setRuntimeWorkspaceStorageBucketDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceStoragePrefixDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncExcludedDirsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncExcludedGlobsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncMaxFileSizeDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncMaxFileCountDraft: Dispatch<SetStateAction<string>>;
  setRuntimeOfficeTemplatesDraft: Dispatch<
    SetStateAction<AdminOfficeTemplateEntry[]>
  >;
  applyCorpIdentityListPayload: (
    data: AdminCorpIdentityListResponse,
  ) => Promise<void>;
  setRuntimeLlmSecurityTimeoutDraft: Dispatch<SetStateAction<string>>;
  setRuntimeLlmSecurityReviewThresholdDraft: Dispatch<SetStateAction<string>>;
  setRuntimeLlmSecurityDenyThresholdDraft: Dispatch<SetStateAction<string>>;
  setRuntimeSecurityAnalyzerChainDraft: Dispatch<SetStateAction<string>>;
  setRuntimeDefaultCompletionDraft: Dispatch<SetStateAction<string>>;
  setRuntimeExtendedCompletionDraft: Dispatch<SetStateAction<string>>;
  setRuntimeApproxCharsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxStringDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxListDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxDictDraft: Dispatch<SetStateAction<string>>;
  setRuntimeScriptOutputDraft: Dispatch<SetStateAction<string>>;
  setRuntimeRequestTimeoutDraft: Dispatch<SetStateAction<string>>;
  setRuntimeSessionCostLimitDraft: Dispatch<SetStateAction<string>>;
  setRuntimeRequestCostLimitDraft: Dispatch<SetStateAction<string>>;
  setRuntimeCacheTtlDraft: Dispatch<SetStateAction<string>>;
  setRuntimeToolsCacheTtlDraft: Dispatch<SetStateAction<string>>;
  setRuntimeToolPlannerTraceCallEnabled: Dispatch<SetStateAction<boolean>>;
  setRuntimeToolPlannerMaxTokensDraft: Dispatch<SetStateAction<string>>;
  setRuntimeToolPlannerTimeoutDraft: Dispatch<SetStateAction<string>>;
};

type RuntimeSettingsDraftArgs = Omit<
  LoadRuntimesTabDataArgs,
  "readJson" | "providers" | "setProviders" | "setRuntimes" | "applyCorpIdentityListPayload"
>;

function fetchRuntimesTabData(readJson: ReadJsonFn, providers: AdminProvider[]) {
  return Promise.all([
    readJson<AdminRuntime[]>("/admin/chat/api/panel/runtimes"),
    readJson<AdminRuntimeSettings>("/admin/chat/api/panel/runtime-settings"),
    readJson<AdminToolResultCompressor[]>(
      "/admin/chat/api/panel/tool-result-compressors",
    ),
    readJson<AdminToolResultCompressionLog[]>(
      "/admin/chat/api/panel/tool-result-compression-log?limit=12",
    ),
    providers.length === 0
      ? readJson<AdminProvider[]>("/admin/chat/api/panel/providers")
      : Promise.resolve(null),
    readJson<AdminCorpIdentityListResponse>(
      "/admin/chat/api/panel/corp-identities",
    ),
  ]);
}

function applyCompressorState(
  args: RuntimeSettingsDraftArgs,
  settings: AdminRuntimeSettings,
  compressorData: AdminToolResultCompressor[],
  compressionLogData: AdminToolResultCompressionLog[],
) {
  args.setRuntimeSettings(settings);
  args.setToolResultCompressors(compressorData);
  args.setToolResultCompressionLogs(compressionLogData);
  args.setToolResultCompressorDrafts(
    Object.fromEntries(
      compressorData.map((item) => [
        item.tool_name,
        {
          strategy: item.strategy,
          config: item.config || {},
          is_active: item.is_active,
        },
      ]),
    ),
  );
}

function applyWorkspaceDrafts(args: RuntimeSettingsDraftArgs, settings: AdminRuntimeSettings) {
  args.setRuntimeGlobalOutputDraft(
    settings.max_output_tokens_default != null
      ? String(settings.max_output_tokens_default)
      : "",
  );
  args.setRuntimeDefaultModelDraft(settings.agent_default_model || "");
  args.setRuntimeAuthOidcOnlyDraft(Boolean(settings.auth_oidc_only));
  args.setRuntimeExecutionProviderDraft(
    settings.execution_runtime_provider || "host",
  );
  args.setRuntimeExecutionDockerImageDraft(
    settings.execution_runtime_docker_image || "python:3.11-slim",
  );
  args.setRuntimeExecutionDockerNetworkDraft(
    settings.execution_runtime_docker_network_mode || "none",
  );
  args.setRuntimeExecutionAllowHostFallback(
    Boolean(settings.execution_runtime_allow_host_fallback),
  );
  args.setRuntimeWorkspaceBaseDirDraft(
    settings.session_workspace_base_dir || "",
  );
  args.setRuntimeWorkspaceMaxAgeDraft(
    String(settings.session_workspace_max_age_hours ?? 24),
  );
  args.setRuntimeWorkspaceStorageBackendDraft(
    settings.session_workspace_storage_backend || "disabled",
  );
  args.setRuntimeWorkspaceStorageBucketDraft(
    settings.session_workspace_storage_bucket || "",
  );
  args.setRuntimeWorkspaceStoragePrefixDraft(
    settings.session_workspace_storage_prefix || "",
  );
  args.setRuntimeWorkspaceSyncExcludedDirsDraft(
    settings.session_workspace_sync_excluded_dirs || "",
  );
  args.setRuntimeWorkspaceSyncExcludedGlobsDraft(
    settings.session_workspace_sync_excluded_globs || "",
  );
  args.setRuntimeWorkspaceSyncMaxFileSizeDraft(
    String(settings.session_workspace_sync_max_file_size_bytes ?? 0),
  );
  args.setRuntimeWorkspaceSyncMaxFileCountDraft(
    String(settings.session_workspace_sync_max_file_count ?? 5000),
  );
  args.setRuntimeOfficeTemplatesDraft(
    settings.office_template_library || [],
  );
}

function applySecurityAndCompletionDrafts(args: RuntimeSettingsDraftArgs, settings: AdminRuntimeSettings) {
  args.setRuntimeLlmSecurityTimeoutDraft(
    String(settings.llm_security_analyzer_timeout_seconds ?? 8),
  );
  args.setRuntimeLlmSecurityReviewThresholdDraft(
    String(settings.llm_security_analyzer_review_threshold ?? 40),
  );
  args.setRuntimeLlmSecurityDenyThresholdDraft(
    String(settings.llm_security_analyzer_deny_threshold ?? 80),
  );
  args.setRuntimeSecurityAnalyzerChainDraft(
    (settings.security_analyzer_chain || []).join(", "),
  );
  args.setRuntimeDefaultCompletionDraft(
    String(settings.default_completion_tokens ?? 4096),
  );
  args.setRuntimeExtendedCompletionDraft(
    String(settings.extended_completion_tokens ?? 8192),
  );
  args.setRuntimeApproxCharsDraft(
    String(settings.approx_chars_per_token ?? 4),
  );
  args.setRuntimeTraceMaxStringDraft(
    String(settings.trace_max_string ?? 16000),
  );
  args.setRuntimeTraceMaxListDraft(
    String(settings.trace_max_list_items ?? 200),
  );
  args.setRuntimeTraceMaxDictDraft(
    String(settings.trace_max_dict_items ?? 120),
  );
}

function applyLimitDrafts(args: RuntimeSettingsDraftArgs, settings: AdminRuntimeSettings) {
  args.setRuntimeScriptOutputDraft(
    String(settings.saved_script_max_output_chars ?? 8000),
  );
  args.setRuntimeRequestTimeoutDraft(
    String(settings.runtime_request_timeout_seconds ?? 90),
  );
  args.setRuntimeSessionCostLimitDraft(
    String(settings.agent_session_cost_limit_usd ?? 5),
  );
  args.setRuntimeRequestCostLimitDraft(
    String(settings.agent_request_cost_limit_usd ?? 1.5),
  );
  args.setRuntimeCacheTtlDraft(
    String(settings.llm_cache_ttl_seconds ?? 300),
  );
  args.setRuntimeToolsCacheTtlDraft(
    String(settings.llm_cache_tools_ttl_seconds ?? 120),
  );
  args.setRuntimeToolPlannerTraceCallEnabled(
    Boolean(settings.llm_tool_planner_trace_call_enabled),
  );
  args.setRuntimeToolPlannerMaxTokensDraft(
    String(settings.llm_tool_planner_max_tokens ?? 900),
  );
  args.setRuntimeToolPlannerTimeoutDraft(
    String(settings.llm_tool_planner_timeout_seconds ?? 30),
  );
}

export async function loadRuntimesTabData(args: LoadRuntimesTabDataArgs) {
  const [
    runtimeData,
    runtimeSettingsData,
    compressorData,
    compressionLogData,
    providerData,
    corpIdentityData,
  ] = await fetchRuntimesTabData(args.readJson, args.providers);
  args.setRuntimes(runtimeData);
  applyCompressorState(args, runtimeSettingsData, compressorData, compressionLogData);
  applyWorkspaceDrafts(args, runtimeSettingsData);
  await args.applyCorpIdentityListPayload(corpIdentityData);
  applySecurityAndCompletionDrafts(args, runtimeSettingsData);
  applyLimitDrafts(args, runtimeSettingsData);
  if (providerData) args.setProviders(providerData);
}
