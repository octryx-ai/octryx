import type { Dispatch, SetStateAction } from "react";
import type { AdminModel, AdminProvider } from "../types/adminPanelTypes.usersProviders";
import { createProviderModelDraftActions } from "./providerModelDraftActions";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type CreateProviderModelActionsArgs = {
  readJson: ReadJsonFn;
  setSyncingProvider: Dispatch<SetStateAction<string | null>>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  loadProviderModels: (providerId: string) => Promise<void>;
  modelBudgetDrafts: Record<string, string>;
  setModelBudgetDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  modelOutputDrafts: Record<string, string>;
  setModelOutputDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  modelPricingInputDrafts: Record<string, string>;
  setModelPricingInputDrafts: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  modelPricingOutputDrafts: Record<string, string>;
  setModelPricingOutputDrafts: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  setModelSort: Dispatch<
    SetStateAction<Record<string, { col: string; dir: "asc" | "desc" }>>
  >;
};

export function createProviderModelActions(args: CreateProviderModelActionsArgs) {
  const {
    handleSaveModelMaxTokens,
    handleSaveModelPlannerBudget,
    handleSaveModelPricingInput,
    handleSaveModelPricingOutput,
  } = createProviderModelDraftActions(args);
  const { handleSyncModels, handleSortModel } = providerSyncActions(args);
  const { handleToggleModel, handleToggleModelCapability } = modelToggleActions(args);
  const handleBulkToggleModels = bulkToggleAction(args);

  return {
    handleBulkToggleModels,
    handleSaveModelMaxTokens,
    handleSaveModelPlannerBudget,
    handleSaveModelPricingInput,
    handleSaveModelPricingOutput,
    handleSortModel,
    handleSyncModels,
    handleToggleModel,
    handleToggleModelCapability,
  };
}

const modelPath = (providerId: string, modelId: string) => `/admin/chat/api/panel/providers/${providerId}/models/${modelId}`;

// Sync a provider's models (its list reloads, its counts follow) and sort a provider's model table.
function providerSyncActions({ readJson, setSyncingProvider, setProviderModels, setProviders, loadProviderModels, setModelSort }: CreateProviderModelActionsArgs) {
  const handleSyncModels = async (providerId: string) => {
    setSyncingProvider(providerId);
    try {
      const result = await readJson<{
        models_added: number;
        total_models: number;
        active_models: number;
      }>(`/admin/chat/api/panel/providers/${providerId}/sync`, {
        method: "POST",
      });
      setProviderModels((prev) => {
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
      await loadProviderModels(providerId);
      setProviders((prev) =>
        prev.map((provider) =>
          provider.id === providerId
            ? { ...provider, model_count: result.total_models, active_model_count: result.active_models }
            : provider,
        ),
      );
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncingProvider(null);
    }
  };

  const handleSortModel = (providerId: string, col: string) => {
    setModelSort((prev) => {
      const current = prev[providerId];
      const dir =
        current?.col === col && current.dir === "asc" ? "desc" : "asc";
      return { ...prev, [providerId]: { col, dir } };
    });
  };
  return { handleSyncModels, handleSortModel };
}

// Switch one model on or off, or one of its capabilities.
function modelToggleActions({ readJson, setProviderModels }: CreateProviderModelActionsArgs) {
  const handleToggleModel = async (providerId: string, modelId: string, active: boolean) => {
    try {
      await readJson(modelPath(providerId, modelId), {
        method: "PUT",
        body: JSON.stringify({ is_active: active }),
      });
      setProviderModels((prev) => ({
        ...prev,
        [providerId]: (prev[providerId] || []).map((model) =>
          model.id === modelId ? { ...model, is_active: active } : model,
        ),
      }));
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed");
    }
  };

  const handleToggleModelCapability = async (
    providerId: string,
    modelId: string,
    field: "supports_tools" | "supports_vision",
    enabled: boolean,
  ) => {
    try {
      const updated = await readJson<Partial<AdminModel>>(modelPath(providerId, modelId), {
        method: "PUT",
        body: JSON.stringify({ [field]: enabled }),
      });
      setProviderModels((prev) => ({
        ...prev,
        [providerId]: (prev[providerId] || []).map((model) =>
          model.id === modelId ? { ...model, [field]: Boolean(updated[field] ?? enabled) } : model,
        ),
      }));
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed");
    }
  };
  return { handleToggleModel, handleToggleModelCapability };
}

// Switch several models one by one; a model that fails is skipped, the provider's active count follows each change.
function bulkToggleAction({ readJson, setProviderModels, setProviders }: CreateProviderModelActionsArgs) {
  return async (providerId: string, targetIds: string[], active: boolean) => {
    for (const modelId of targetIds) {
      try {
        await readJson(modelPath(providerId, modelId), {
          method: "PUT",
          body: JSON.stringify({ is_active: active }),
        });
        setProviderModels((prev) => ({
          ...prev,
          [providerId]: (prev[providerId] || []).map((model) =>
            model.id === modelId ? { ...model, is_active: active } : model,
          ),
        }));
        setProviders((prev) =>
          prev.map((provider) => {
            if (provider.id !== providerId) return provider;
            const delta = active ? 1 : -1;
            return { ...provider, active_model_count: Math.max(0, provider.active_model_count + delta) };
          }),
        );
      } catch {
        // Ignore per-model errors in bulk path.
      }
    }
  };
}
