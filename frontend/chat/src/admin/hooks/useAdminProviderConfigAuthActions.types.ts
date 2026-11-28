import type { Dispatch, SetStateAction } from "react";

export type CreateProviderConfigAuthActionsArgs = {
  expandedProvider: string | null;
  setExpandedProvider: Dispatch<SetStateAction<string | null>>;
  loadProviderModels: (providerId: string) => Promise<void>;
};
