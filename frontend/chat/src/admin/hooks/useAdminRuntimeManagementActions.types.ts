import type { Dispatch, SetStateAction } from "react";
import type { AdminOfficeTemplateEntry, AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type RuntimeSettingsActionArgs = {
  readJson: ReadJsonFn;
  runtimeGlobalOutputDraft: string;
  runtimeDefaultModelDraft: string;
  runtimeAuthOidcOnlyDraft: boolean;
  runtimeExecutionProviderDraft: "host" | "docker";
  runtimeExecutionDockerImageDraft: string;
  runtimeExecutionDockerNetworkDraft: "none" | "bridge" | "host";
  runtimeExecutionAllowHostFallback: boolean;
  runtimeWorkspaceBaseDirDraft: string;
  runtimeWorkspaceMaxAgeDraft: string;
  runtimeWorkspaceStorageBackendDraft: AdminRuntimeSettings["session_workspace_storage_backend"];
  runtimeWorkspaceStorageBucketDraft: string;
  runtimeWorkspaceStoragePrefixDraft: string;
  runtimeWorkspaceSyncExcludedDirsDraft: string;
  runtimeWorkspaceSyncExcludedGlobsDraft: string;
  runtimeWorkspaceSyncMaxFileSizeDraft: string;
  runtimeWorkspaceSyncMaxFileCountDraft: string;
  runtimeOfficeTemplatesDraft: AdminOfficeTemplateEntry[];
  sanitizeOfficeTemplateKey: (value: string) => string;
  runtimeLlmSecurityTimeoutDraft: string;
  runtimeLlmSecurityReviewThresholdDraft: string;
  runtimeLlmSecurityDenyThresholdDraft: string;
  runtimeSecurityAnalyzerChainDraft: string;
  runtimeDefaultCompletionDraft: string;
  runtimeExtendedCompletionDraft: string;
  runtimeApproxCharsDraft: string;
  runtimeTraceMaxStringDraft: string;
  runtimeTraceMaxListDraft: string;
  runtimeTraceMaxDictDraft: string;
  runtimeScriptOutputDraft: string;
  runtimeRequestTimeoutDraft: string;
  runtimeSessionCostLimitDraft: string;
  runtimeRequestCostLimitDraft: string;
  runtimeCacheTtlDraft: string;
  runtimeToolsCacheTtlDraft: string;
  runtimeToolPlannerTraceCallEnabled: boolean;
  runtimeToolPlannerMaxTokensDraft: string;
  runtimeToolPlannerTimeoutDraft: string;
  setRuntimeSettings: Dispatch<SetStateAction<AdminRuntimeSettings>>;
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
