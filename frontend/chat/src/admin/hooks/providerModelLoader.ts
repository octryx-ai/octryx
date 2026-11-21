// Provider models loader: fetch a provider's models once and seed the budget, output and pricing drafts.
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminProviderManagementArgs } from "./useAdminProviderManagement.types";

type ProviderModelLoaderArgs = Pick<
  UseAdminProviderManagementArgs,
  | "readJson"
  | "providerModels"
  | "setModelsLoading"
  | "setProviderModels"
  | "setModelBudgetDrafts"
  | "setModelOutputDrafts"
  | "setModelPricingInputDrafts"
  | "setModelPricingOutputDrafts"
>;

export function createProviderModelLoader({
  readJson,
  providerModels,
  setModelsLoading,
  setProviderModels,
  setModelBudgetDrafts,
  setModelOutputDrafts,
  setModelPricingInputDrafts,
  setModelPricingOutputDrafts,
}: ProviderModelLoaderArgs) {
  const loadProviderModels = async (providerId: string) => {
    if (providerModels[providerId]?.length) return;
    setModelsLoading(providerId);
    try {
      const data = await readJson<AdminModel[]>(
        `/admin/chat/api/panel/providers/${providerId}/models`,
      );
      setProviderModels((prev) => ({ ...prev, [providerId]: data }));
      setModelBudgetDrafts((prev) => {
        const next = { ...prev };
        for (const model of data) {
          next[model.id] =
            model.planner_context_budget != null
              ? String(model.planner_context_budget)
              : "";
        }
        return next;
      });
      setModelOutputDrafts((prev) => {
        const next = { ...prev };
        for (const model of data) {
          next[model.id] =
            model.max_tokens_per_request != null
              ? String(model.max_tokens_per_request)
              : "";
        }
        return next;
      });
      setModelPricingInputDrafts((prev) => {
        const next = { ...prev };
        for (const model of data) {
          next[model.id] =
            model.pricing_input != null ? String(model.pricing_input) : "";
        }
        return next;
      });
      setModelPricingOutputDrafts((prev) => {
        const next = { ...prev };
        for (const model of data) {
          next[model.id] =
            model.pricing_output != null ? String(model.pricing_output) : "";
        }
        return next;
      });
    } catch (err) {
      window.alert(
        err instanceof Error ? err.message : "Failed to load models",
      );
    } finally {
      setModelsLoading(null);
    }
  };

  return loadProviderModels;
}
