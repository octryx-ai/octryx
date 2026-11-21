// Runtime admin state: runtimes, compression, execution, workspace, security, limits and planner drafts.
import { useState } from "react";
import { DEFAULT_RUNTIME_SETTINGS } from "../config/adminPanelDefaults";
import type { AdminRuntime, AdminRuntimeSettings, AdminToolResultCompressor, AdminToolResultCompressionLog, RuntimePanelSection } from "../types/adminPanelTypes.runtimeCorp";

type CompressorDraft = { strategy: string; config: Record<string, unknown>; is_active: boolean };

function useRuntimeCoreState() {
  const [runtimes, setRuntimes] = useState<AdminRuntime[]>([]);
  const [toolResultCompressors, setToolResultCompressors] = useState<AdminToolResultCompressor[]>([]);
  const [toolResultCompressionLogs, setToolResultCompressionLogs] = useState<AdminToolResultCompressionLog[]>([]);
  const [toolResultCompressorDrafts, setToolResultCompressorDrafts] = useState<Record<string, CompressorDraft>>({});
  const [toolResultCompressionSaving, setToolResultCompressionSaving] = useState<string | null>(null);
  const [runtimeFormProvider, setRuntimeFormProvider] = useState("");
  const [runtimeFormModel, setRuntimeFormModel] = useState("");
  const [runtimeFormPrimary, setRuntimeFormPrimary] = useState(false);
  const [runtimeFormLoading, setRuntimeFormLoading] = useState(false);
  const [runtimeFormError, setRuntimeFormError] = useState<string | null>(null);
  const [showAddRuntime, setShowAddRuntime] = useState(false);
  const [runtimeSettings, setRuntimeSettings] = useState<AdminRuntimeSettings>(DEFAULT_RUNTIME_SETTINGS);
  const [runtimeGlobalOutputDraft, setRuntimeGlobalOutputDraft] = useState("");
  const [runtimeDefaultModelDraft, setRuntimeDefaultModelDraft] = useState("");
  const [runtimeExecutionProviderDraft, setRuntimeExecutionProviderDraft] =
    useState<AdminRuntimeSettings["execution_runtime_provider"]>("host");
  const [runtimeAuthOidcOnlyDraft, setRuntimeAuthOidcOnlyDraft] = useState(false);
  const [runtimeExecutionDockerImageDraft, setRuntimeExecutionDockerImageDraft] = useState("python:3.11-slim");
  const [runtimeExecutionDockerNetworkDraft, setRuntimeExecutionDockerNetworkDraft] =
    useState<AdminRuntimeSettings["execution_runtime_docker_network_mode"]>("none");
  const [runtimeExecutionAllowHostFallback, setRuntimeExecutionAllowHostFallback] = useState(false);
  return {
    runtimes, setRuntimes, toolResultCompressors, setToolResultCompressors, toolResultCompressionLogs,
    setToolResultCompressionLogs, toolResultCompressorDrafts, setToolResultCompressorDrafts,
    toolResultCompressionSaving, setToolResultCompressionSaving, runtimeFormProvider, setRuntimeFormProvider,
    runtimeFormModel, setRuntimeFormModel, runtimeFormPrimary, setRuntimeFormPrimary, runtimeFormLoading,
    setRuntimeFormLoading, runtimeFormError, setRuntimeFormError, showAddRuntime, setShowAddRuntime,
    runtimeSettings, setRuntimeSettings, runtimeGlobalOutputDraft, setRuntimeGlobalOutputDraft,
    runtimeDefaultModelDraft, setRuntimeDefaultModelDraft, runtimeExecutionProviderDraft,
    setRuntimeExecutionProviderDraft, runtimeAuthOidcOnlyDraft, setRuntimeAuthOidcOnlyDraft,
    runtimeExecutionDockerImageDraft, setRuntimeExecutionDockerImageDraft, runtimeExecutionDockerNetworkDraft,
    setRuntimeExecutionDockerNetworkDraft, runtimeExecutionAllowHostFallback, setRuntimeExecutionAllowHostFallback,
  };
}

function useRuntimeWorkspaceState() {
  const [runtimeWorkspaceBaseDirDraft, setRuntimeWorkspaceBaseDirDraft] = useState("");
  const [runtimeWorkspaceMaxAgeDraft, setRuntimeWorkspaceMaxAgeDraft] = useState("24");
  const [runtimeWorkspaceStorageBackendDraft, setRuntimeWorkspaceStorageBackendDraft] =
    useState<AdminRuntimeSettings["session_workspace_storage_backend"]>("disabled");
  const [runtimeWorkspaceStorageBucketDraft, setRuntimeWorkspaceStorageBucketDraft] = useState("");
  const [runtimeWorkspaceStoragePrefixDraft, setRuntimeWorkspaceStoragePrefixDraft] = useState("");
  const [runtimeWorkspaceSyncExcludedDirsDraft, setRuntimeWorkspaceSyncExcludedDirsDraft] = useState("");
  const [runtimeWorkspaceSyncExcludedGlobsDraft, setRuntimeWorkspaceSyncExcludedGlobsDraft] = useState("");
  const [runtimeWorkspaceSyncMaxFileSizeDraft, setRuntimeWorkspaceSyncMaxFileSizeDraft] = useState("0");
  const [runtimeWorkspaceSyncMaxFileCountDraft, setRuntimeWorkspaceSyncMaxFileCountDraft] = useState("5000");
  const [runtimeWorkspaceCleanupBusy, setRuntimeWorkspaceCleanupBusy] = useState(false);
  return {
    runtimeWorkspaceBaseDirDraft, setRuntimeWorkspaceBaseDirDraft, runtimeWorkspaceMaxAgeDraft,
    setRuntimeWorkspaceMaxAgeDraft, runtimeWorkspaceStorageBackendDraft, setRuntimeWorkspaceStorageBackendDraft,
    runtimeWorkspaceStorageBucketDraft, setRuntimeWorkspaceStorageBucketDraft, runtimeWorkspaceStoragePrefixDraft,
    setRuntimeWorkspaceStoragePrefixDraft, runtimeWorkspaceSyncExcludedDirsDraft,
    setRuntimeWorkspaceSyncExcludedDirsDraft, runtimeWorkspaceSyncExcludedGlobsDraft,
    setRuntimeWorkspaceSyncExcludedGlobsDraft, runtimeWorkspaceSyncMaxFileSizeDraft,
    setRuntimeWorkspaceSyncMaxFileSizeDraft, runtimeWorkspaceSyncMaxFileCountDraft,
    setRuntimeWorkspaceSyncMaxFileCountDraft, runtimeWorkspaceCleanupBusy, setRuntimeWorkspaceCleanupBusy,
  };
}

function useRuntimeSecurityLimitsState() {
  const [runtimeLlmSecurityTimeoutDraft, setRuntimeLlmSecurityTimeoutDraft] = useState("8");
  const [runtimeLlmSecurityReviewThresholdDraft, setRuntimeLlmSecurityReviewThresholdDraft] = useState("40");
  const [runtimeLlmSecurityDenyThresholdDraft, setRuntimeLlmSecurityDenyThresholdDraft] = useState("80");
  const [runtimeSecurityAnalyzerChainDraft, setRuntimeSecurityAnalyzerChainDraft] =
    useState("exec_policy, secret_access, command_guardrail");
  const [runtimeDefaultCompletionDraft, setRuntimeDefaultCompletionDraft] = useState("4096");
  const [runtimeExtendedCompletionDraft, setRuntimeExtendedCompletionDraft] = useState("8192");
  const [runtimeApproxCharsDraft, setRuntimeApproxCharsDraft] = useState("4");
  const [runtimeTraceMaxStringDraft, setRuntimeTraceMaxStringDraft] = useState("16000");
  const [runtimeTraceMaxListDraft, setRuntimeTraceMaxListDraft] = useState("200");
  const [runtimeTraceMaxDictDraft, setRuntimeTraceMaxDictDraft] = useState("120");
  const [runtimeScriptOutputDraft, setRuntimeScriptOutputDraft] = useState("8000");
  const [runtimeRequestTimeoutDraft, setRuntimeRequestTimeoutDraft] = useState("90");
  const [runtimeSessionCostLimitDraft, setRuntimeSessionCostLimitDraft] = useState("5");
  const [runtimeRequestCostLimitDraft, setRuntimeRequestCostLimitDraft] = useState("1.5");
  const [runtimeCostScopeProjectId, setRuntimeCostScopeProjectId] = useState("");
  const [runtimeCacheTtlDraft, setRuntimeCacheTtlDraft] = useState("300");
  const [runtimeToolsCacheTtlDraft, setRuntimeToolsCacheTtlDraft] = useState("120");
  return {
    runtimeLlmSecurityTimeoutDraft, setRuntimeLlmSecurityTimeoutDraft, runtimeLlmSecurityReviewThresholdDraft,
    setRuntimeLlmSecurityReviewThresholdDraft, runtimeLlmSecurityDenyThresholdDraft,
    setRuntimeLlmSecurityDenyThresholdDraft, runtimeSecurityAnalyzerChainDraft, setRuntimeSecurityAnalyzerChainDraft,
    runtimeDefaultCompletionDraft, setRuntimeDefaultCompletionDraft,
    runtimeExtendedCompletionDraft, setRuntimeExtendedCompletionDraft, runtimeApproxCharsDraft,
    setRuntimeApproxCharsDraft, runtimeTraceMaxStringDraft, setRuntimeTraceMaxStringDraft, runtimeTraceMaxListDraft,
    setRuntimeTraceMaxListDraft, runtimeTraceMaxDictDraft, setRuntimeTraceMaxDictDraft, runtimeScriptOutputDraft,
    setRuntimeScriptOutputDraft, runtimeRequestTimeoutDraft, setRuntimeRequestTimeoutDraft,
    runtimeSessionCostLimitDraft, setRuntimeSessionCostLimitDraft, runtimeRequestCostLimitDraft,
    setRuntimeRequestCostLimitDraft, runtimeCostScopeProjectId, setRuntimeCostScopeProjectId, runtimeCacheTtlDraft,
    setRuntimeCacheTtlDraft, runtimeToolsCacheTtlDraft, setRuntimeToolsCacheTtlDraft,
  };
}

function useRuntimePlannerPanelState() {
  const [runtimeToolPlannerTraceCallEnabled, setRuntimeToolPlannerTraceCallEnabled] = useState(false);
  const [runtimeToolPlannerMaxTokensDraft, setRuntimeToolPlannerMaxTokensDraft] = useState("900");
  const [runtimeToolPlannerTimeoutDraft, setRuntimeToolPlannerTimeoutDraft] = useState("30");
  const [runtimePanelSection, setRuntimePanelSection] = useState<RuntimePanelSection>("priority");
  const [editingRuntimeTags, setEditingRuntimeTags] = useState<string | null>(null);
  const [runtimeTagsInput, setRuntimeTagsInput] = useState("");
  return {
    runtimeToolPlannerTraceCallEnabled, setRuntimeToolPlannerTraceCallEnabled, runtimeToolPlannerMaxTokensDraft,
    setRuntimeToolPlannerMaxTokensDraft, runtimeToolPlannerTimeoutDraft, setRuntimeToolPlannerTimeoutDraft,
    runtimePanelSection, setRuntimePanelSection, editingRuntimeTags, setEditingRuntimeTags, runtimeTagsInput,
    setRuntimeTagsInput,
  };
}

export function useAdminRuntimeState() {
  return {
    ...useRuntimeCoreState(),
    ...useRuntimeWorkspaceState(),
    ...useRuntimeSecurityLimitsState(),
    ...useRuntimePlannerPanelState(),
  };
}
