import type { Dispatch, SetStateAction } from "react";
import type { AdminModel, AdminProvider } from "../types/adminPanelTypes.usersProviders";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type UseAdminProviderManagementArgs = {
  readJson: ReadJsonFn;
  providers: AdminProvider[];
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  providerModels: Record<string, AdminModel[]>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
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
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
  newProviderDisplay: string;
  setNewProviderDisplay: Dispatch<SetStateAction<string>>;
  newModelId: string;
  setNewModelId: Dispatch<SetStateAction<string>>;
  newModelDisplay: string;
  setNewModelDisplay: Dispatch<SetStateAction<string>>;
  newModelTools: boolean;
  setNewModelTools: Dispatch<SetStateAction<boolean>>;
  newModelMaxTokens: string;
  setNewModelMaxTokens: Dispatch<SetStateAction<string>>;
  setShowAddModel: Dispatch<SetStateAction<string | null>>;
};
