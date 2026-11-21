// Saves a provider's Bedrock prompt caching config from its draft.
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ProviderDraft } from "./useAdminProviderManagement.types";
import type { CreateProviderConfigAuthActionsArgs } from "./useAdminProviderConfigAuthActions.types";
import {
  buildBedrockDraftFromUpdatedProvider,
  buildBedrockProviderConfigUpdate,
} from "./useAdminProviderConfigAuthActions.helpers";

type Args = CreateProviderConfigAuthActionsArgs;

async function saveProviderConfig(
  args: Args,
  provider: AdminProvider,
  payload: unknown,
  nextDraft: (updated: AdminProvider) => ProviderDraft,
  failure: string,
) {
  args.setSavingProviderConfig(provider.id);
  try {
    const updated = await args.readJson<AdminProvider>(`/admin/chat/api/panel/providers/${provider.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    args.setProviders((prev) => prev.map((item) => (item.id === provider.id ? updated : item)));
    args.setProviderDrafts((prev) => ({ ...prev, [provider.id]: nextDraft(updated) }));
  } catch (err) {
    window.alert(err instanceof Error ? err.message : failure);
  } finally {
    args.setSavingProviderConfig(null);
  }
}

export async function saveBedrockProviderConfig(args: Args, provider: AdminProvider) {
  const draft = args.providerDrafts[provider.id];
  if (!draft) return;
  const payload = buildBedrockProviderConfigUpdate(provider, draft);
  await saveProviderConfig(
    args,
    provider,
    payload,
    (updated) => buildBedrockDraftFromUpdatedProvider(updated, draft),
    "Failed to save Bedrock prompt caching config",
  );
}
