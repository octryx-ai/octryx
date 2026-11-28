import type { CreateProviderConfigAuthActionsArgs } from "./useAdminProviderConfigAuthActions.types";

export function createProviderConfigAuthActions(args: CreateProviderConfigAuthActionsArgs) {
  const handleToggleProvider = async (providerId: string) => {
    if (args.expandedProvider === providerId) {
      args.setExpandedProvider(null);
      return;
    }
    args.setExpandedProvider(providerId);
    await args.loadProviderModels(providerId);
  };

  return { handleToggleProvider };
}
