// Provider management: composes provider toggle, model, cache rate, runtime and LiteLLM gateway actions.
import { createLiteLlmGatewayActions } from "./useAdminLiteLlmGatewayActions";
import { createProviderConfigAuthActions } from "./useAdminProviderConfigAuthActions";
import { createProviderModelActions } from "./useAdminProviderModelActions";
import { createModelCacheRateActions } from "./useAdminProviderModelCacheRates";
import { createProviderRuntimeActions } from "./useAdminProviderRuntimeActions";
import { createProviderModelLoader } from "./providerModelLoader";
import type { UseAdminProviderManagementArgs } from "./useAdminProviderManagement.types";

// Provider toggle and model actions, both reloading models through the shared loader.
function providerConfigAndModelActions(args: UseAdminProviderManagementArgs) {
  const loadProviderModels = createProviderModelLoader(args);
  const { handleToggleProvider } = createProviderConfigAuthActions({ ...args, loadProviderModels });
  const m = createProviderModelActions({ ...args, loadProviderModels });
  const { handleSaveModelCacheRates } = createModelCacheRateActions(args);
  return {
    handleToggleProvider,
    handleBulkToggleModels: m.handleBulkToggleModels,
    handleSaveModelMaxTokens: m.handleSaveModelMaxTokens,
    handleSaveModelPricingInput: m.handleSaveModelPricingInput,
    handleSaveModelPricingOutput: m.handleSaveModelPricingOutput,
    handleSortModel: m.handleSortModel,
    handleSyncModels: m.handleSyncModels,
    handleToggleModel: m.handleToggleModel,
    handleToggleModelCapability: m.handleToggleModelCapability,
    handleSaveModelCacheRates,
  };
}

export function useAdminProviderManagement(args: UseAdminProviderManagementArgs) {
  const r = createProviderRuntimeActions(args);
  const g = createLiteLlmGatewayActions(args);
  return {
    ...providerConfigAndModelActions(args),
    handleAddModel: r.handleAddModel,
    handleDeleteProvider: r.handleDeleteProvider,
    handleCreateLiteLlmGatewayProvider: g.handleCreateLiteLlmGatewayProvider,
    handleUpdateLiteLlmGatewayProvider: g.handleUpdateLiteLlmGatewayProvider,
  };
}
