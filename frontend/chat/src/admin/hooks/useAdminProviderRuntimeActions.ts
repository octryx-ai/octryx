import type { FormEvent } from "react";
import type { CreateProviderRuntimeActionsArgs } from "./useAdminProviderRuntimeActions.types";
import { addProviderModel, deleteProvider } from "./providerRuntimeRequests";

export function createProviderRuntimeActions(args: CreateProviderRuntimeActionsArgs) {
  return {
    handleAddModel: (event: FormEvent, providerId: string) => addProviderModel(args, event, providerId),
    handleDeleteProvider: (providerId: string, displayName: string) => deleteProvider(args, providerId, displayName),
  };
}
