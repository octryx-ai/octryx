import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import { saveBedrockProviderConfig } from "./providerConfigSaveActions";
import { createProviderCreateActions } from "./useAdminProviderCreateActions";
import { createProviderGoogleAuthActions } from "./useAdminProviderGoogleAuthActions";
import type { ProviderDraft } from "./useAdminProviderManagement.types";
import type { CreateProviderConfigAuthActionsArgs } from "./useAdminProviderConfigAuthActions.types";
import {
  buildProviderDraftFromProvider,
  normalizeProviderDraft,
} from "./useAdminProviderConfigAuthActions.helpers";

export function createProviderConfigAuthActions(args: CreateProviderConfigAuthActionsArgs) {
  const { setExpandedProvider, setProviderDrafts } = args;
  const handleToggleProvider = async (providerId: string) => {
    if (args.expandedProvider === providerId) {
      setExpandedProvider(null);
      return;
    }
    const provider = args.providers.find((item) => item.id === providerId);
    if (provider) {
      setProviderDrafts((prev) => ({
        ...prev,
        [providerId]:
          prev[providerId] ||
          buildProviderDraftFromProvider(provider),
      }));
    }
    setExpandedProvider(providerId);
    await args.loadProviderModels(providerId);
  };

  const handleProviderDraftChange = (providerId: string, field: keyof ProviderDraft, value: string) => {
    setProviderDrafts((prev) => ({
      ...prev,
      [providerId]: { ...normalizeProviderDraft(prev[providerId]), [field]: value },
    }));
  };

  const {
    handleGoogleConnect,
    handleSaveGoogleProviderConfig,
  } = createProviderGoogleAuthActions(args);

  // The create actions read the add-provider form fields and setters from the same args.
  const { handleAddProvider, handleSaveApiKey } = createProviderCreateActions(args);

  return {
    handleAddProvider,
    handleGoogleConnect,
    handleProviderDraftChange,
    handleSaveApiKey,
    handleSaveBedrockProviderConfig: (provider: AdminProvider) => saveBedrockProviderConfig(args, provider),
    handleSaveGoogleProviderConfig,
    handleToggleProvider,
  };
}
