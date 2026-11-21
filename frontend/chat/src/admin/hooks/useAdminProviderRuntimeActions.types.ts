import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { AdminModel, AdminProvider, LocalBootstrapStatus } from "../types/adminPanelTypes.usersProviders";
import type { AdminTab } from "../types/adminPanelTypes.governance";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type CreateProviderRuntimeActionsArgs = {
  readJson: ReadJsonFn;
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
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
  setNewProviderDriver: Dispatch<SetStateAction<string>>;
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
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
};
