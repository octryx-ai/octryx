// The identity provider requests behind useAdminIdentityProviders: load the list, register an OIDC provider and save
// one provider's draft. Each keeps the list, the drafts, the error and the loading marker in step.
import type { Dispatch, SetStateAction } from "react";

import type { AdminIdentityProviderRow, AdminReadJsonFn } from "./identityTypes";
import { mappingRecord, mappingRows } from "./identityMappingRows";
import type { IdentityProviderMappingDraft } from "./useAdminIdentityProviders";

const DEFAULT_CLAIM_MAPPINGS = {
  subject: "sub",
  email: "email",
  username: "preferred_username",
  display_name: "name",
  groups: "groups",
};

export function createDraft(
  provider: AdminIdentityProviderRow,
): IdentityProviderMappingDraft {
  return {
    name: provider.name || "",
    providerType: provider.providerType || "oidc",
    issuerUrl: provider.issuerUrl || "",
    discoveryUrl: provider.discoveryUrl || "",
    clientId: provider.clientId || "",
    scopes: (provider.scopes || []).join(", "),
    claimMappings: {
      ...DEFAULT_CLAIM_MAPPINGS,
      ...(provider.claimMappings || {}),
    },
    groupRoleMappings: mappingRows(provider.groupRoleMappings),
    groupGroupMappings: mappingRows(provider.groupGroupMappings),
    defaultRoles: new Set(provider.defaultRoles || []),
    defaultGroupIds: new Set(provider.defaultGroupIds || []),
    autoProvisionUsers: Boolean(provider.autoProvisionUsers),
    isActive: Boolean(provider.isActive),
  };
}

export type ProviderSetters = {
  setProviders: Dispatch<SetStateAction<AdminIdentityProviderRow[]>>;
  setProviderDrafts: Dispatch<SetStateAction<Record<string, IdentityProviderMappingDraft>>>;
  setProviderLoading: Dispatch<SetStateAction<string | null>>;
  setProviderError: Dispatch<SetStateAction<string | null>>;
};

export type NewIdentityProvider = {
  name: string;
  issuerUrl: string;
  discoveryUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
};

const scopeList = (scopes: string) => scopes
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

export async function loadProviders(readJson: AdminReadJsonFn, setters: ProviderSetters) {
  const { setProviders, setProviderDrafts, setProviderLoading, setProviderError } = setters;
  setProviderLoading("load");
  try {
    const data = await readJson<AdminIdentityProviderRow[]>(
      "/admin/chat/api/panel/identity-providers",
    );
    const rows = Array.isArray(data) ? data : [];
    setProviders(rows);
    setProviderDrafts(
      Object.fromEntries(
        rows.map((provider) => [provider.id, createDraft(provider)]),
      ),
    );
    setProviderError(null);
  } catch (error) {
    setProviderError(
      error instanceof Error
        ? error.message
        : "Failed to load identity providers",
    );
  } finally {
    setProviderLoading(null);
  }
}

export async function createProvider(readJson: AdminReadJsonFn, payload: NewIdentityProvider, setters: ProviderSetters) {
  const { setProviders, setProviderDrafts, setProviderLoading, setProviderError } = setters;
  setProviderLoading("create");
  try {
    const created = await readJson<AdminIdentityProviderRow>(
      "/admin/chat/api/panel/identity-providers",
      {
        method: "POST",
        body: JSON.stringify({
          name: payload.name,
          provider_type: "oidc",
          issuer_url: payload.issuerUrl,
          discovery_url: payload.discoveryUrl,
          client_id: payload.clientId,
          client_secret: payload.clientSecret || undefined,
          scopes: scopeList(payload.scopes),
          claim_mappings: DEFAULT_CLAIM_MAPPINGS,
          auto_provision_users: true,
          is_active: true,
        }),
      },
    );
    setProviders((current) =>
      [...current, created].sort((a, b) => a.name.localeCompare(b.name)),
    );
    setProviderDrafts((current) => ({
      ...current,
      [created.id]: createDraft(created),
    }));
    setProviderError(null);
  } catch (error) {
    setProviderError(
      error instanceof Error
        ? error.message
        : "Failed to create identity provider",
    );
  } finally {
    setProviderLoading(null);
  }
}

// The PUT body of a provider: its draft with the mappings as records and the sets as lists.
function providerSaveBody(draft: IdentityProviderMappingDraft) {
  return {
    name: draft.name,
    provider_type: draft.providerType,
    issuer_url: draft.issuerUrl,
    discovery_url: draft.discoveryUrl,
    client_id: draft.clientId,
    scopes: scopeList(draft.scopes),
    claim_mappings: draft.claimMappings,
    group_role_mappings: mappingRecord(draft.groupRoleMappings),
    group_group_mappings: mappingRecord(draft.groupGroupMappings),
    default_roles: Array.from(draft.defaultRoles),
    default_group_ids: Array.from(draft.defaultGroupIds),
    auto_provision_users: draft.autoProvisionUsers,
    is_active: draft.isActive,
  };
}

export async function saveProvider(
  readJson: AdminReadJsonFn,
  provider: AdminIdentityProviderRow,
  draft: IdentityProviderMappingDraft | undefined,
  setters: ProviderSetters,
) {
  if (!draft) return;
  const { setProviders, setProviderDrafts, setProviderLoading, setProviderError } = setters;
  setProviderLoading(`save:${provider.id}`);
  try {
    const updated = await readJson<AdminIdentityProviderRow>(
      `/admin/chat/api/panel/identity-providers/${provider.id}`,
      {
        method: "PUT",
        body: JSON.stringify(providerSaveBody(draft)),
      },
    );
    setProviders((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    setProviderDrafts((current) => ({
      ...current,
      [updated.id]: createDraft(updated),
    }));
    setProviderError(null);
  } catch (error) {
    setProviderError(
      error instanceof Error
        ? error.message
        : "Failed to save identity provider",
    );
  } finally {
    setProviderLoading(null);
  }
}
