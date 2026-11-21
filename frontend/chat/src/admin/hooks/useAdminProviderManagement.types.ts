import type { Dispatch, SetStateAction } from "react";
import type { AdminModel, AdminProvider, LocalBootstrapStatus } from "../types/adminPanelTypes.usersProviders";
import type { AdminTab } from "../types/adminPanelTypes.governance";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type ProviderDraft = {
  auth_mode: string;
  google_oauth_client_id: string;
  google_oauth_client_secret: string;
  google_cloud_project: string;
  bedrock_prompt_cache_enabled: string;
  bedrock_prompt_cache_ttl: string;
  bedrock_prompt_cache_min_tokens: string;
  aws_access_key_id: string;
  aws_secret_access_key: string;
  aws_session_token: string;
};

export type CopilotFlow = {
  providerId: string;
  flowId: string;
  userCode: string;
  verificationUri: string;
  interval: number;
  status: "pending" | "waiting" | "connected" | "failed";
  error?: string;
  login?: string;
};

export type UseAdminProviderManagementArgs = {
  readJson: ReadJsonFn;
  providers: AdminProvider[];
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  localBootstrap: LocalBootstrapStatus | null;
  setLocalBootstrap: Dispatch<SetStateAction<LocalBootstrapStatus | null>>;
  setLocalBootstrapActionLoading: Dispatch<SetStateAction<string | null>>;
  setLocalBootstrapError: Dispatch<SetStateAction<string | null>>;
  localBootstrapEndpointDraft: string;
  localBootstrapModelDraft: string;
  localBootstrapDisplayDraft: string;
  localBootstrapPullModel: boolean;
  localBootstrapMakePrimary: boolean;
  refreshBootstrapContext: () => Promise<void>;
  loadLocalBootstrapState: () => Promise<void>;
  loadSetupGuide: () => Promise<void>;
  setTab: Dispatch<SetStateAction<AdminTab>>;
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  providerDrafts: Record<string, ProviderDraft>;
  setProviderDrafts: Dispatch<SetStateAction<Record<string, ProviderDraft>>>;
  setSavingProviderConfig: Dispatch<SetStateAction<string | null>>;
  setGoogleConnectLoading: Dispatch<SetStateAction<string | null>>;
  providerModels: Record<string, AdminModel[]>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
  modelBudgetDrafts: Record<string, string>;
  setModelBudgetDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  modelOutputDrafts: Record<string, string>;
  setModelOutputDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  modelPricingInputDrafts: Record<string, string>;
  setModelPricingInputDrafts: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  modelPricingOutputDrafts: Record<string, string>;
  setModelPricingOutputDrafts: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  setModelsLoading: Dispatch<SetStateAction<string | null>>;
  setSyncingProvider: Dispatch<SetStateAction<string | null>>;
  setModelSort: Dispatch<
    SetStateAction<Record<string, { col: string; dir: "asc" | "desc" }>>
  >;
  newKeyValue: string;
  setEditingKey: Dispatch<SetStateAction<string | null>>;
  setNewKeyValue: Dispatch<SetStateAction<string>>;
  setProviderFormError: Dispatch<SetStateAction<string | null>>;
  setProviderFormLoading: Dispatch<SetStateAction<boolean>>;
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
  newProviderDriver: string;
  setNewProviderDriver: Dispatch<SetStateAction<string>>;
  newProviderDisplay: string;
  setNewProviderDisplay: Dispatch<SetStateAction<string>>;
  newProviderAuthMode: string;
  setNewProviderAuthMode: Dispatch<SetStateAction<string>>;
  newProviderKey: string;
  setNewProviderKey: Dispatch<SetStateAction<string>>;
  newProviderSecretKey: string;
  setNewProviderSecretKey: Dispatch<SetStateAction<string>>;
  newProviderSessionToken: string;
  setNewProviderSessionToken: Dispatch<SetStateAction<string>>;
  newProviderRegion: string;
  setNewProviderRegion: Dispatch<SetStateAction<string>>;
  newProviderArn: string;
  setNewProviderArn: Dispatch<SetStateAction<string>>;
  newProviderEndpointUrl: string;
  setNewProviderEndpointUrl: Dispatch<SetStateAction<string>>;
  newGoogleClientId: string;
  setNewGoogleClientId: Dispatch<SetStateAction<string>>;
  newGoogleClientSecret: string;
  setNewGoogleClientSecret: Dispatch<SetStateAction<string>>;
  newGoogleCloudProject: string;
  setNewGoogleCloudProject: Dispatch<SetStateAction<string>>;
  newModelId: string;
  setNewModelId: Dispatch<SetStateAction<string>>;
  newModelDisplay: string;
  setNewModelDisplay: Dispatch<SetStateAction<string>>;
  newModelTools: boolean;
  setNewModelTools: Dispatch<SetStateAction<boolean>>;
  newModelPlannerBudget: string;
  setNewModelPlannerBudget: Dispatch<SetStateAction<string>>;
  newModelMaxTokens: string;
  setNewModelMaxTokens: Dispatch<SetStateAction<string>>;
  setShowAddModel: Dispatch<SetStateAction<string | null>>;
  copilotFlow: CopilotFlow | null;
  setCopilotFlow: Dispatch<SetStateAction<CopilotFlow | null>>;
};
