// Provider runtime requests: health refresh, local runtime start/stop, model pull, delete provider, add model.
import type { FormEvent } from "react";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import type { CreateProviderRuntimeActionsArgs } from "./useAdminProviderRuntimeActions.types";

type Args = CreateProviderRuntimeActionsArgs;

type ProviderHealthResult = {
  health_status: string;
  last_health_check_at: string;
  last_health_error: string;
  endpoint_url: string;
  binary_path?: string;
  config_json?: Record<string, unknown>;
  capabilities_json?: Record<string, unknown>;
};

export async function refreshProviderHealth(a: Args, providerId: string) {
  try {
    const result = await a.readJson<ProviderHealthResult>(
      `/admin/chat/api/panel/providers/${providerId}/health`,
      { method: "POST" },
    );
    a.setProviders((prev) =>
      prev.map((provider) =>
        provider.id === providerId
          ? {
              ...provider,
              health_status: result.health_status,
              last_health_check_at: result.last_health_check_at,
              last_health_error: result.last_health_error,
              endpoint_url: result.endpoint_url,
              binary_path: result.binary_path || provider.binary_path,
              config_json: result.config_json || provider.config_json,
              capabilities_json: result.capabilities_json || provider.capabilities_json,
            }
          : provider,
      ),
    );
    if (a.localBootstrap?.provider_id === providerId) {
      await a.loadLocalBootstrapState();
    }
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Health check failed");
  }
}

export async function startLocalRuntime(a: Args, providerId: string) {
  try {
    await a.readJson(`/admin/chat/api/panel/providers/${providerId}/start-local-runtime`, { method: "POST" });
    await refreshProviderHealth(a, providerId);
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed to start local runtime");
  }
}

export async function stopLocalRuntime(a: Args, providerId: string) {
  try {
    await a.readJson(`/admin/chat/api/panel/providers/${providerId}/stop-local-runtime`, { method: "POST" });
    a.setProviders((prev) =>
      prev.map((provider) =>
        provider.id === providerId
          ? {
              ...provider,
              health_status: "stopped",
              last_health_error: "",
              last_health_check_at: new Date().toISOString(),
              capabilities_json: { ...provider.capabilities_json, available_models: [] },
            }
          : provider,
      ),
    );
    if (a.localBootstrap?.provider_id === providerId) {
      await a.loadLocalBootstrapState();
    }
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed to stop local runtime");
  }
}

export async function pullProviderModel(a: Args, providerId: string, defaultModelId: string) {
  const modelId = window.prompt("Model ID to pull from Ollama", defaultModelId || "gemma4");
  if (!modelId) return;
  try {
    await a.readJson(`/admin/chat/api/panel/providers/${providerId}/pull-model`, {
      method: "POST",
      body: JSON.stringify({ model_id: modelId.trim() }),
    });
    await a.refreshBootstrapContext();
    window.alert(`Model '${modelId.trim()}' was queued for pull.`);
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Model pull failed");
  }
}

export async function deleteProvider(a: Args, providerId: string, displayName: string) {
  if (!window.confirm(`Delete provider "${displayName}" and all its models?`)) {
    return;
  }
  try {
    await a.readJson(`/admin/chat/api/panel/providers/${providerId}`, { method: "DELETE" });
    a.setProviders((prev) => prev.filter((provider) => provider.id !== providerId));
    void a.loadSetupGuide();
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
        planner_context_budget: a.newModelPlannerBudget ? Number(a.newModelPlannerBudget) : null,
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
    a.setNewModelPlannerBudget("");
    a.setNewModelMaxTokens("");
    a.setShowAddModel(null);
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed");
  }
}
