// Provider model draft actions: save planner budget, output token limit and pricing drafts of one model.
import type { Dispatch, SetStateAction } from "react";
import type { AdminModel } from "../types/adminPanelTypes.usersProviders";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

type Drafts = Record<string, string>;
type SetDrafts = Dispatch<SetStateAction<Drafts>>;

type ProviderModelDraftActionsArgs = {
  readJson: ReadJsonFn;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
  modelBudgetDrafts: Drafts;
  setModelBudgetDrafts: SetDrafts;
  modelOutputDrafts: Drafts;
  setModelOutputDrafts: SetDrafts;
  modelPricingInputDrafts: Drafts;
  setModelPricingInputDrafts: SetDrafts;
  modelPricingOutputDrafts: Drafts;
  setModelPricingOutputDrafts: SetDrafts;
};

type DraftField = "planner_context_budget" | "max_tokens_per_request" | "pricing_input" | "pricing_output";

export function createProviderModelDraftActions({
  readJson,
  setProviderModels,
  modelBudgetDrafts,
  setModelBudgetDrafts,
  modelOutputDrafts,
  setModelOutputDrafts,
  modelPricingInputDrafts,
  setModelPricingInputDrafts,
  modelPricingOutputDrafts,
  setModelPricingOutputDrafts,
}: ProviderModelDraftActionsArgs) {
  const save = (field: DraftField, drafts: Drafts, setDrafts: SetDrafts) =>
    (providerId: string, modelId: string) => saveModelDraft({ readJson, setProviderModels, field, drafts, setDrafts, providerId, modelId });
  const handleSaveModelPlannerBudget = save("planner_context_budget", modelBudgetDrafts, setModelBudgetDrafts);
  const handleSaveModelMaxTokens = save("max_tokens_per_request", modelOutputDrafts, setModelOutputDrafts);
  const handleSaveModelPricingInput = save("pricing_input", modelPricingInputDrafts, setModelPricingInputDrafts);
  const handleSaveModelPricingOutput = save("pricing_output", modelPricingOutputDrafts, setModelPricingOutputDrafts);

  return {
    handleSaveModelMaxTokens,
    handleSaveModelPlannerBudget,
    handleSaveModelPricingInput,
    handleSaveModelPricingOutput,
  };
}

// One model field saved from its draft (empty clears it); the model and the draft take the stored value.
async function saveModelDraft({ readJson, setProviderModels, field, drafts, setDrafts, providerId, modelId }: {
  readJson: ReadJsonFn;
  setProviderModels: ProviderModelDraftActionsArgs["setProviderModels"];
  field: DraftField;
  drafts: Drafts;
  setDrafts: SetDrafts;
  providerId: string;
  modelId: string;
}) {
  const draft = (drafts[modelId] || "").trim();
  try {
    const updated = await readJson<Record<DraftField, number | null>>(
      `/admin/chat/api/panel/providers/${providerId}/models/${modelId}`,
      {
        method: "PUT",
        body: JSON.stringify({
          [field]: draft ? Number(draft) : null,
        }),
      },
    );
    setProviderModels((prev) => ({
      ...prev,
      [providerId]: (prev[providerId] || []).map((model) =>
        model.id === modelId ? { ...model, [field]: updated[field] } : model,
      ),
    }));
    setDrafts((prev) => ({
      ...prev,
      [modelId]: updated[field] != null ? String(updated[field]) : "",
    }));
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed");
  }
}
