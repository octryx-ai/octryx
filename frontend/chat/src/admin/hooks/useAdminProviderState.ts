import { useState } from "react";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import { orderKeys } from "./orderKeys";

function useProviderModelState() {
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [providerModels, setProviderModels] = useState<
    Record<string, AdminModel[]>
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
    expandedProvider, setExpandedProvider, providerModels, setProviderModels,
    modelOutputDrafts, setModelOutputDrafts, modelPricingInputDrafts, setModelPricingInputDrafts, modelPricingOutputDrafts,
    setModelPricingOutputDrafts, modelsLoading, setModelsLoading, syncingProvider, setSyncingProvider,
  };
}

function useNewProviderFormState() {
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [newProviderDisplay, setNewProviderDisplay] = useState("");
  return { showAddProvider, setShowAddProvider, newProviderDisplay, setNewProviderDisplay };
}

function useProviderModelFormState() {
  const [showAddModel, setShowAddModel] = useState<string | null>(null);
  const [newModelId, setNewModelId] = useState("");
  const [newModelDisplay, setNewModelDisplay] = useState("");
  const [newModelTools, setNewModelTools] = useState(true);
  const [newModelMaxTokens, setNewModelMaxTokens] = useState("");
  const [modelFilter, setModelFilter] = useState<Record<string, string>>({});
  const [modelSort, setModelSort] = useState<
    Record<string, { col: string; dir: "asc" | "desc" }>
  >({});
  return {
    showAddModel, setShowAddModel, newModelId, setNewModelId, newModelDisplay, setNewModelDisplay,
    newModelTools, setNewModelTools, newModelMaxTokens, setNewModelMaxTokens,
    modelFilter, setModelFilter, modelSort, setModelSort,
  };
}

// The order of the returned keys, as callers have always seen it.
const PROVIDER_STATE_KEYS = [
  "expandedProvider", "setExpandedProvider", "modelFilter", "setModelFilter",
  "modelOutputDrafts", "setModelOutputDrafts", "modelPricingInputDrafts", "setModelPricingInputDrafts", "modelPricingOutputDrafts",
  "setModelPricingOutputDrafts", "modelSort", "setModelSort", "modelsLoading", "setModelsLoading", "newModelDisplay",
  "setNewModelDisplay", "newModelId", "setNewModelId", "newModelMaxTokens", "setNewModelMaxTokens",
  "newModelTools", "setNewModelTools", "newProviderDisplay", "setNewProviderDisplay",
  "providerModels", "setProviderModels", "showAddModel", "setShowAddModel", "showAddProvider", "setShowAddProvider",
  "syncingProvider", "setSyncingProvider",
] as const;

export function useAdminProviderState() {
  const models = useProviderModelState();
  const form = useNewProviderFormState();
  const modelForm = useProviderModelFormState();
  return orderKeys({ ...models, ...form, ...modelForm }, PROVIDER_STATE_KEYS);
}
