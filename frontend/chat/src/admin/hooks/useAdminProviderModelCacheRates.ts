import type { Dispatch, SetStateAction } from "react";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type CacheRateBody = { pricing_cache_read: number | null; pricing_cache_write: number | null };

// Saves a model's prompt-cache rate pair and keeps the loaded catalog in step with what the server stored.
// Errors propagate so the cell can show them next to the fields.
export function createModelCacheRateActions({
  readJson,
  setProviderModels,
}: {
  readJson: ReadJsonFn;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
}) {
  const handleSaveModelCacheRates = async (providerId: string, modelId: string, body: CacheRateBody) => {
    const updated = await readJson<CacheRateBody>(`/admin/chat/api/panel/providers/${providerId}/models/${modelId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    setProviderModels((prev) => ({
      ...prev,
      [providerId]: (prev[providerId] || []).map((model) =>
        model.id === modelId
          ? { ...model, pricing_cache_read: updated.pricing_cache_read, pricing_cache_write: updated.pricing_cache_write }
          : model,
      ),
    }));
  };
  return { handleSaveModelCacheRates };
}
