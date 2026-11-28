import type { Dispatch, SetStateAction } from "react";
import type { AdminModel, AdminProvider } from "../types/adminPanelTypes.usersProviders";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type CreateProviderRuntimeActionsArgs = {
  readJson: ReadJsonFn;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
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
