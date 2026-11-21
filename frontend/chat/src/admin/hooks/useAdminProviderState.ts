import { useState } from "react";
import { DEFAULT_PROVIDER_CREATE_DRIVER } from "../components/providerTab/providerCreateChoices";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import type {
  CopilotFlow,
  ProviderDraft,
} from "./useAdminProviderManagement.types";
import { orderKeys } from "./orderKeys";

function useProviderModelState() {
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [providerModels, setProviderModels] = useState<
    Record<string, AdminModel[]>
  >({});
  const [modelBudgetDrafts, setModelBudgetDrafts] = useState<
    Record<string, string>
  >({});
  const [modelOutputDrafts, setModelOutputDrafts] = useState<
    Record<string, string>
  >({});
  const [modelPricingInputDrafts, setModelPricingInputDrafts] = useState<
    Record<string, string>
  >({});
  const [modelPricingOutputDrafts, setModelPricingOutputDrafts] = useState<
    Record<string, string>
  >({});
  const [modelsLoading, setModelsLoading] = useState<string | null>(null);
  const [syncingProvider, setSyncingProvider] = useState<string | null>(null);
  return {
    expandedProvider, setExpandedProvider, providerModels, setProviderModels, modelBudgetDrafts, setModelBudgetDrafts,
    modelOutputDrafts, setModelOutputDrafts, modelPricingInputDrafts, setModelPricingInputDrafts, modelPricingOutputDrafts,
    setModelPricingOutputDrafts, modelsLoading, setModelsLoading, syncingProvider, setSyncingProvider,
  };
}

function useNewProviderFormState() {
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [newProviderDriver, setNewProviderDriver] = useState(DEFAULT_PROVIDER_CREATE_DRIVER);
  const [newProviderDisplay, setNewProviderDisplay] = useState("");
  const [newProviderAuthMode, setNewProviderAuthMode] = useState("api_key");
  const [newProviderKey, setNewProviderKey] = useState("");
  const [newProviderSecretKey, setNewProviderSecretKey] = useState("");
  const [newProviderSessionToken, setNewProviderSessionToken] = useState("");
  const [newProviderRegion, setNewProviderRegion] = useState("");
  const [newProviderArn, setNewProviderArn] = useState("");
  const [newProviderEndpointUrl, setNewProviderEndpointUrl] = useState("");
  const [newGoogleClientId, setNewGoogleClientId] = useState("");
  const [newGoogleClientSecret, setNewGoogleClientSecret] = useState("");
  const [newGoogleCloudProject, setNewGoogleCloudProject] = useState("");
  const [providerFormLoading, setProviderFormLoading] = useState(false);
  const [providerFormError, setProviderFormError] = useState<string | null>(
    null,
  );
  return {
    showAddProvider, setShowAddProvider, newProviderDriver, setNewProviderDriver, newProviderDisplay, setNewProviderDisplay,
    newProviderAuthMode, setNewProviderAuthMode, newProviderKey, setNewProviderKey, newProviderSecretKey, setNewProviderSecretKey,
    newProviderSessionToken, setNewProviderSessionToken, newProviderRegion, setNewProviderRegion, newProviderArn, setNewProviderArn,
    newProviderEndpointUrl, setNewProviderEndpointUrl, newGoogleClientId, setNewGoogleClientId, newGoogleClientSecret,
    setNewGoogleClientSecret, newGoogleCloudProject, setNewGoogleCloudProject, providerFormLoading, setProviderFormLoading,
    providerFormError, setProviderFormError,
  };
}

function useProviderEditState() {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [newKeyValue, setNewKeyValue] = useState("");
  const [providerDrafts, setProviderDrafts] = useState<
    Record<string, ProviderDraft>
  >({});
  const [savingProviderConfig, setSavingProviderConfig] = useState<
    string | null
  >(null);
  const [googleConnectLoading, setGoogleConnectLoading] = useState<
    string | null
  >(null);
  const [showAddModel, setShowAddModel] = useState<string | null>(null);
  const [copilotFlow, setCopilotFlow] = useState<CopilotFlow | null>(null);
  const [newModelId, setNewModelId] = useState("");
  const [newModelDisplay, setNewModelDisplay] = useState("");
  const [newModelTools, setNewModelTools] = useState(true);
  const [newModelPlannerBudget, setNewModelPlannerBudget] = useState("");
  const [newModelMaxTokens, setNewModelMaxTokens] = useState("");
  const [modelFilter, setModelFilter] = useState<Record<string, string>>({});
  const [modelSort, setModelSort] = useState<
    Record<string, { col: string; dir: "asc" | "desc" }>
  >({});
  return {
    editingKey, setEditingKey, newKeyValue, setNewKeyValue, providerDrafts, setProviderDrafts, savingProviderConfig,
    setSavingProviderConfig, googleConnectLoading, setGoogleConnectLoading,
    showAddModel, setShowAddModel, copilotFlow, setCopilotFlow, newModelId, setNewModelId, newModelDisplay, setNewModelDisplay,
    newModelTools, setNewModelTools, newModelPlannerBudget, setNewModelPlannerBudget, newModelMaxTokens, setNewModelMaxTokens,
    modelFilter, setModelFilter, modelSort, setModelSort,
  };
}

// The order of the returned keys, as callers have always seen it.
const PROVIDER_STATE_KEYS = [
  "copilotFlow", "setCopilotFlow", "editingKey", "setEditingKey", "expandedProvider", "setExpandedProvider",
  "googleConnectLoading", "setGoogleConnectLoading", "modelBudgetDrafts",
  "setModelBudgetDrafts", "modelFilter", "setModelFilter", "modelOutputDrafts", "setModelOutputDrafts", "modelPricingInputDrafts",
  "setModelPricingInputDrafts", "modelPricingOutputDrafts", "setModelPricingOutputDrafts", "modelSort", "setModelSort",
  "modelsLoading", "setModelsLoading", "newGoogleClientId", "setNewGoogleClientId", "newGoogleCloudProject",
  "setNewGoogleCloudProject", "newGoogleClientSecret", "setNewGoogleClientSecret", "newKeyValue", "setNewKeyValue",
  "newModelDisplay", "setNewModelDisplay", "newModelId", "setNewModelId", "newModelMaxTokens", "setNewModelMaxTokens",
  "newModelPlannerBudget", "setNewModelPlannerBudget", "newModelTools", "setNewModelTools", "newProviderArn", "setNewProviderArn",
  "newProviderAuthMode", "setNewProviderAuthMode", "newProviderDisplay", "setNewProviderDisplay", "newProviderEndpointUrl",
  "setNewProviderEndpointUrl", "newProviderKey", "setNewProviderKey", "newProviderSecretKey", "setNewProviderSecretKey",
  "newProviderSessionToken", "setNewProviderSessionToken", "newProviderDriver", "setNewProviderDriver", "newProviderRegion",
  "setNewProviderRegion", "providerDrafts", "setProviderDrafts", "providerFormError", "setProviderFormError",
  "providerFormLoading", "setProviderFormLoading", "providerModels", "setProviderModels", "savingProviderConfig",
  "setSavingProviderConfig", "showAddModel", "setShowAddModel", "showAddProvider", "setShowAddProvider", "syncingProvider",
  "setSyncingProvider",
] as const;

export function useAdminProviderState() {
  const models = useProviderModelState();
  const form = useNewProviderFormState();
  const edit = useProviderEditState();
  return orderKeys({ ...models, ...form, ...edit }, PROVIDER_STATE_KEYS);
}
