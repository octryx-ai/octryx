import type { FormEvent } from "react";
import { DEFAULT_PROVIDER_CREATE_DRIVER } from "../components/providerTab/providerCreateChoices";
import type { CreateProviderRuntimeActionsArgs } from "./useAdminProviderRuntimeActions.types";
import { createLocalBootstrapActions } from "./localBootstrapActions";
import {
  addProviderModel,
  deleteProvider,
  pullProviderModel,
  refreshProviderHealth,
  startLocalRuntime,
  stopLocalRuntime,
} from "./providerRuntimeRequests";

export function createProviderRuntimeActions(args: CreateProviderRuntimeActionsArgs) {
  const { setTab, setShowAddProvider, setNewProviderDriver } = args;
  const { handleCheckLocalBootstrap, handleSetupLocalBootstrap } = createLocalBootstrapActions(args);

  const handleSetupGuideAction = async (action: string) => {
    if (action === "configure_local_anchor") {
      await handleSetupLocalBootstrap();
      return;
    }
    if (action === "open_api_provider_form") {
      setShowAddProvider(true);
      setNewProviderDriver(DEFAULT_PROVIDER_CREATE_DRIVER);
      return;
    }
    if (action === "open_runtime_tab" || action === "open_explain") {
      setTab("modelOrder");
    }
    if (action === "open_model_catalog") {
      setTab("modelCatalog");
    }
  };

  return {
    handleAddModel: (event: FormEvent, providerId: string) => addProviderModel(args, event, providerId),
    handleCheckLocalBootstrap,
    handleDeleteProvider: (providerId: string, displayName: string) => deleteProvider(args, providerId, displayName),
    handlePullProviderModel: (providerId: string, defaultModelId: string) =>
      pullProviderModel(args, providerId, defaultModelId),
    handleRefreshProviderHealth: (providerId: string) => refreshProviderHealth(args, providerId),
    handleSetupGuideAction,
    handleSetupLocalBootstrap,
    handleStartLocalRuntime: (providerId: string) => startLocalRuntime(args, providerId),
    handleStopLocalRuntime: (providerId: string) => stopLocalRuntime(args, providerId),
  };
}
