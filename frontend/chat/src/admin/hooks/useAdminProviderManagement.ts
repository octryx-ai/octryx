// Provider management: composes config/auth, model, cache rate, runtime, gateway and Copilot actions.
import { useEffect, useRef, type MutableRefObject } from "react";
import { createCopilotActions } from "./useAdminProviderCopilotActions";
import { createLiteLlmGatewayActions } from "./useAdminLiteLlmGatewayActions";
import { createProviderConfigAuthActions } from "./useAdminProviderConfigAuthActions";
import { createProviderModelActions } from "./useAdminProviderModelActions";
import { createModelCacheRateActions } from "./useAdminProviderModelCacheRates";
import { createProviderRuntimeActions } from "./useAdminProviderRuntimeActions";
import { createProviderModelLoader } from "./providerModelLoader";
import type { UseAdminProviderManagementArgs } from "./useAdminProviderManagement.types";

type CopilotPollRef = MutableRefObject<ReturnType<typeof setInterval> | null>;

// Provider config/auth and model actions, both reloading models through the shared loader.
function providerConfigAndModelActions(args: UseAdminProviderManagementArgs) {
  const loadProviderModels = createProviderModelLoader(args);
  const c = createProviderConfigAuthActions({ ...args, loadProviderModels });
  const m = createProviderModelActions({ ...args, loadProviderModels });
  const { handleSaveModelCacheRates } = createModelCacheRateActions(args);
  return {
    handleAddProvider: c.handleAddProvider,
    handleGoogleConnect: c.handleGoogleConnect,
    handleProviderDraftChange: c.handleProviderDraftChange,
    handleSaveApiKey: c.handleSaveApiKey,
    handleSaveBedrockProviderConfig: c.handleSaveBedrockProviderConfig,
    handleSaveGoogleProviderConfig: c.handleSaveGoogleProviderConfig,
    handleToggleProvider: c.handleToggleProvider,
    handleBulkToggleModels: m.handleBulkToggleModels,
    handleSaveModelMaxTokens: m.handleSaveModelMaxTokens,
    handleSaveModelPlannerBudget: m.handleSaveModelPlannerBudget,
    handleSaveModelPricingInput: m.handleSaveModelPricingInput,
    handleSaveModelPricingOutput: m.handleSaveModelPricingOutput,
    handleSortModel: m.handleSortModel,
    handleSyncModels: m.handleSyncModels,
    handleToggleModel: m.handleToggleModel,
    handleToggleModelCapability: m.handleToggleModelCapability,
    handleSaveModelCacheRates,
  };
}

// Local runtime/bootstrap, LiteLLM gateway and Copilot device-flow actions.
function providerRuntimeActions(args: UseAdminProviderManagementArgs, copilotPollRef: CopilotPollRef) {
  const r = createProviderRuntimeActions(args);
  const g = createLiteLlmGatewayActions(args);
  const { handleCopilotConnect, handleCopilotDisconnect } = createCopilotActions({ ...args, copilotPollRef });
  return {
    handleAddModel: r.handleAddModel,
    handleCheckLocalBootstrap: r.handleCheckLocalBootstrap,
    handleDeleteProvider: r.handleDeleteProvider,
    handlePullProviderModel: r.handlePullProviderModel,
    handleRefreshProviderHealth: r.handleRefreshProviderHealth,
    handleSetupGuideAction: r.handleSetupGuideAction,
    handleSetupLocalBootstrap: r.handleSetupLocalBootstrap,
    handleStartLocalRuntime: r.handleStartLocalRuntime,
    handleStopLocalRuntime: r.handleStopLocalRuntime,
    handleCreateLiteLlmGatewayProvider: g.handleCreateLiteLlmGatewayProvider,
    handleUpdateLiteLlmGatewayProvider: g.handleUpdateLiteLlmGatewayProvider,
    handleCopilotConnect,
    handleCopilotDisconnect,
  };
}

export function useAdminProviderManagement(args: UseAdminProviderManagementArgs) {
  const copilotPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(
    () => () => {
      if (copilotPollRef.current) {
        clearInterval(copilotPollRef.current);
      }
    },
    [],
  );

  return {
    ...providerConfigAndModelActions(args),
    ...providerRuntimeActions(args, copilotPollRef),
  };
}
