import { useCallback, useState } from "react";

import type {
  AdminIdentityGroupRow,
  AdminIdentityProviderRow,
  AdminReadJsonFn,
  AdminRoleRow,
} from "./identityTypes";
import type { MappingRow } from "./identityMappingRows";
import { createProvider, loadProviders, saveProvider, type NewIdentityProvider } from "./identityProviderRequests";

export type IdentityProviderMappingDraft = {
  name: string;
  providerType: string;
  issuerUrl: string;
  discoveryUrl: string;
  clientId: string;
  scopes: string;
  claimMappings: Record<string, string>;
  groupRoleMappings: MappingRow[];
  groupGroupMappings: MappingRow[];
  defaultRoles: Set<string>;
  defaultGroupIds: Set<string>;
  autoProvisionUsers: boolean;
  isActive: boolean;
};

type UseAdminIdentityProvidersResult = {
  providers: AdminIdentityProviderRow[];
  providerDrafts: Record<string, IdentityProviderMappingDraft>;
  providerLoading: string | null;
  providerError: string | null;
  loadIdentityProviders: () => Promise<void>;
  createIdentityProvider: (payload: NewIdentityProvider) => Promise<void>;
  updateDraft: (
    providerId: string,
    updater: (
      draft: IdentityProviderMappingDraft,
    ) => IdentityProviderMappingDraft,
  ) => void;
  saveIdentityProvider: (
    provider: AdminIdentityProviderRow,
    roles: AdminRoleRow[],
    groups: AdminIdentityGroupRow[],
  ) => Promise<void>;
};

export function useAdminIdentityProviders(
  readJson: AdminReadJsonFn,
): UseAdminIdentityProvidersResult {
  const [providers, setProviders] = useState<AdminIdentityProviderRow[]>([]);
  const [providerDrafts, setProviderDrafts] = useState<
    Record<string, IdentityProviderMappingDraft>
  >({});
  const [providerLoading, setProviderLoading] = useState<string | null>(null);
  const [providerError, setProviderError] = useState<string | null>(null);

  const loadIdentityProviders = useCallback(
    () => loadProviders(readJson, { setProviders, setProviderDrafts, setProviderLoading, setProviderError }),
    [readJson],
  );

  const updateDraft = useCallback(
    (
      providerId: string,
      updater: (
        draft: IdentityProviderMappingDraft,
      ) => IdentityProviderMappingDraft,
    ) => {
      setProviderDrafts((current) => {
        const draft = current[providerId];
        if (!draft) return current;
        return { ...current, [providerId]: updater(draft) };
      });
    },
    [],
  );

  const createIdentityProvider = useCallback(
    (payload: NewIdentityProvider) =>
      createProvider(readJson, payload, { setProviders, setProviderDrafts, setProviderLoading, setProviderError }),
    [readJson],
  );

  const saveIdentityProvider = useCallback(
    (
      provider: AdminIdentityProviderRow,
      _roles: AdminRoleRow[],
      _groups: AdminIdentityGroupRow[],
    ) => saveProvider(readJson, provider, providerDrafts[provider.id], {
      setProviders, setProviderDrafts, setProviderLoading, setProviderError,
    }),
    [providerDrafts, readJson],
  );

  return {
    providers,
    providerDrafts,
    providerLoading,
    providerError,
    loadIdentityProviders,
    createIdentityProvider,
    updateDraft,
    saveIdentityProvider,
  };
}
