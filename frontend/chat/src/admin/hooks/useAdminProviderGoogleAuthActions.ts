import type { Dispatch, SetStateAction } from "react";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ProviderDraft } from "./useAdminProviderManagement.types";
import type { ReadJsonFn } from "./useAdminProviderConfigAuthActions.types";

type CreateProviderGoogleAuthActionsArgs = {
  readJson: ReadJsonFn;
  providerDrafts: Record<string, ProviderDraft>;
  setProviderDrafts: Dispatch<SetStateAction<Record<string, ProviderDraft>>>;
  setSavingProviderConfig: Dispatch<SetStateAction<string | null>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setGoogleConnectLoading: Dispatch<SetStateAction<string | null>>;
};

type GoogleAuthArgs = CreateProviderGoogleAuthActionsArgs;

export function createProviderGoogleAuthActions(args: CreateProviderGoogleAuthActionsArgs) {
  const { setGoogleConnectLoading } = args;
  const handleSaveGoogleProviderConfig = (providerId: string) => saveGoogleProviderConfig(args, providerId);

  const handleGoogleConnect = (providerId: string) => {
    setGoogleConnectLoading(providerId);
    window.location.assign(
      `/admin/chat/api/panel/providers/${providerId}/google/oauth/start`,
    );
  };

  return {
    handleGoogleConnect,
    handleSaveGoogleProviderConfig,
  };
}

async function saveGoogleProviderConfig({ readJson, providerDrafts, setProviderDrafts, setSavingProviderConfig, setProviders }: GoogleAuthArgs,
  providerId: string) {
  const draft = providerDrafts[providerId];
  if (!draft) return;
  setSavingProviderConfig(providerId);
  try {
    const updated = await readJson<AdminProvider>(
      `/admin/chat/api/panel/providers/${providerId}`,
      {
        method: "PUT",
        body: JSON.stringify({
          auth_mode: draft.auth_mode,
          google_oauth_client_id: draft.google_oauth_client_id || undefined,
          google_oauth_client_secret:
            draft.google_oauth_client_secret || undefined,
          google_cloud_project: draft.google_cloud_project || undefined,
        }),
      },
    );
    setProviders((prev) =>
      prev.map((item) => (item.id === providerId ? updated : item)),
    );
    setProviderDrafts((prev) => ({
      ...prev,
      [providerId]: {
        ...draft,
        google_oauth_client_secret: "",
      },
    }));
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed to save Google provider config");
  } finally {
    setSavingProviderConfig(null);
  }
}
