// Provider requests: delete a provider, add a model to it.
import type { FormEvent } from "react";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import type { CreateProviderRuntimeActionsArgs } from "./useAdminProviderRuntimeActions.types";

type Args = CreateProviderRuntimeActionsArgs;

export async function deleteProvider(a: Args, providerId: string, displayName: string) {
  if (!window.confirm(`Delete provider "${displayName}" and all its models?`)) {
    return;
  }
  try {
    await a.readJson(`/admin/chat/api/panel/providers/${providerId}`, { method: "DELETE" });
    a.setProviders((prev) => prev.filter((provider) => provider.id !== providerId));
    a.setProviderModels((prev) => {
      const next = { ...prev };
      delete next[providerId];
      return next;
    });
    if (a.expandedProvider === providerId) {
      a.setExpandedProvider(null);
    }
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed");
  }
}

export async function addProviderModel(a: Args, event: FormEvent, providerId: string) {
  event.preventDefault();
  try {
    const model = await a.readJson<AdminModel>(`/admin/chat/api/panel/providers/${providerId}/models`, {
      method: "POST",
      body: JSON.stringify({
        model_id: a.newModelId,
        display_name: a.newModelDisplay || a.newModelId,
        supports_tools: a.newModelTools,
        max_tokens_per_request: a.newModelMaxTokens ? Number(a.newModelMaxTokens) : null,
      }),
    });
    a.setProviderModels((prev) => ({ ...prev, [providerId]: [...(prev[providerId] || []), model] }));
    a.setProviders((prev) =>
      prev.map((provider) =>
        provider.id === providerId ? { ...provider, model_count: provider.model_count + 1 } : provider,
      ),
    );
    a.setNewModelId("");
    a.setNewModelDisplay("");
    a.setNewModelTools(true);
    a.setNewModelMaxTokens("");
    a.setShowAddModel(null);
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed");
  }
}
