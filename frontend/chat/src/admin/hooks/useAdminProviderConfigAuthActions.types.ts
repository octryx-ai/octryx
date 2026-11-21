import type { Dispatch, SetStateAction } from "react";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ProviderDraft } from "./useAdminProviderManagement.types";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type CreateProviderConfigAuthActionsArgs = {
  readJson: ReadJsonFn;
  providers: AdminProvider[];
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  setProviderDrafts: Dispatch<SetStateAction<Record<string, ProviderDraft>>>;
  providerDrafts: Record<string, ProviderDraft>;
  loadProviderModels: (providerId: string) => Promise<void>;
  setSavingProviderConfig: Dispatch<SetStateAction<string | null>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setGoogleConnectLoading: Dispatch<SetStateAction<string | null>>;
  newKeyValue: string;
  setEditingKey: Dispatch<SetStateAction<string | null>>;
  setNewKeyValue: Dispatch<SetStateAction<string>>;
  setProviderFormError: Dispatch<SetStateAction<string | null>>;
  setProviderFormLoading: Dispatch<SetStateAction<boolean>>;
  newProviderDriver: string;
  newProviderDisplay: string;
  newProviderEndpointUrl: string;
  newProviderAuthMode: string;
  newProviderKey: string;
  newProviderSecretKey: string;
  newProviderSessionToken: string;
  newProviderRegion: string;
  newProviderArn: string;
  newGoogleClientId: string;
  newGoogleClientSecret: string;
  newGoogleCloudProject: string;
  setNewProviderDriver: Dispatch<SetStateAction<string>>;
  setNewProviderDisplay: Dispatch<SetStateAction<string>>;
  setNewProviderAuthMode: Dispatch<SetStateAction<string>>;
  setNewProviderKey: Dispatch<SetStateAction<string>>;
  setNewProviderSecretKey: Dispatch<SetStateAction<string>>;
  setNewProviderSessionToken: Dispatch<SetStateAction<string>>;
  setNewProviderRegion: Dispatch<SetStateAction<string>>;
  setNewProviderArn: Dispatch<SetStateAction<string>>;
  setNewProviderEndpointUrl: Dispatch<SetStateAction<string>>;
  setNewGoogleClientId: Dispatch<SetStateAction<string>>;
  setNewGoogleClientSecret: Dispatch<SetStateAction<string>>;
  setNewGoogleCloudProject: Dispatch<SetStateAction<string>>;
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
  loadSetupGuide: () => Promise<void>;
};
