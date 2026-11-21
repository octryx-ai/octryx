// Agent step form actions: open, close, save, delete and reorder the steps of an agent.
import type { FormEvent } from "react";
import type { PanelAgentStep } from "../types/adminPanelTypes.agents";
import {
  buildAgentStepPayload,
  buildReorderedStepIds,
  hydrateAgentStepFormState,
  resetAgentStepFormState,
} from "./useAdminAgentForms.helpers";
import type { UseAdminAgentFormsArgs } from "./useAdminAgentForms.types";

export function createAgentStepFormActions(
  args: UseAdminAgentFormsArgs,
  refreshAgentsPanel: () => Promise<void>,
) {
  const agentStepFormSetters = {
    setEditingAgentStep: args.setEditingAgentStep,
    setAgentStepFormName: args.setAgentStepFormName,
    setAgentStepFormType: args.setAgentStepFormType,
    setAgentStepFormInstructions: args.setAgentStepFormInstructions,
    setAgentStepFormSuccessCriteria: args.setAgentStepFormSuccessCriteria,
    setAgentStepFormAllowedTools: args.setAgentStepFormAllowedTools,
    setAgentStepFormConfig: args.setAgentStepFormConfig,
    setAgentStepFormEnabled: args.setAgentStepFormEnabled,
    setAgentStepFormError: args.setAgentStepFormError,
  };

  const resetAgentStepForm = () => {
    resetAgentStepFormState(
      agentStepFormSetters,
      args.agentBuilderMeta?.step_type_options?.[0] || "analysis",
    );
  };

  const handleOpenAgentStepForm = (
    agentId: string,
    step?: PanelAgentStep | null,
  ) => {
    args.setAgentStepFormFor(agentId);
    if (!step) {
      resetAgentStepForm();
      return;
    }
    hydrateAgentStepFormState(agentStepFormSetters, step);
  };

  const closeAgentStepForm = () => {
    args.setAgentStepFormFor(null);
    args.setEditingAgentStep(null);
    args.setAgentStepFormError(null);
  };

  const handleSaveAgentStep = async (event: FormEvent) => {
    event.preventDefault();
    if (!args.agentStepFormFor) return;
    args.setAgentStepFormLoading(true);
    args.setAgentStepFormError(null);
    try {
      const payload = buildAgentStepPayload({
        name: args.agentStepFormName,
        type: args.agentStepFormType,
        instructions: args.agentStepFormInstructions,
        successCriteria: args.agentStepFormSuccessCriteria,
        allowedTools: args.agentStepFormAllowedTools,
        config: args.agentStepFormConfig,
        enabled: args.agentStepFormEnabled,
      });
      await args.readJson<PanelAgentStep>(
        args.editingAgentStep
          ? `/admin/chat/api/panel/agents/${args.agentStepFormFor}/steps/${args.editingAgentStep.id}`
          : `/admin/chat/api/panel/agents/${args.agentStepFormFor}/steps`,
        {
          method: args.editingAgentStep ? "PUT" : "POST",
          body: JSON.stringify(payload),
        },
      );
      await refreshAgentsPanel();
      closeAgentStepForm();
    } catch (error) {
      args.setAgentStepFormError(
        error instanceof Error ? error.message : "Step save failed",
      );
    } finally {
      args.setAgentStepFormLoading(false);
    }
  };

  const handleDeleteAgentStep = async (
    agentId: string,
    step: PanelAgentStep,
  ) => {
    if (!window.confirm(`Delete step "${step.name}"?`)) return;
    await args.readJson(
      `/admin/chat/api/panel/agents/${agentId}/steps/${step.id}`,
      { method: "DELETE" },
    );
    await refreshAgentsPanel();
  };

  const handleMoveAgentStep = async (
    agentId: string,
    stepId: string,
    direction: "up" | "down",
  ) => {
    const order = buildReorderedStepIds(
      args.panelAgents,
      agentId,
      stepId,
      direction,
    );
    if (!order) return;
    await args.readJson(
      `/admin/chat/api/panel/agents/${agentId}/steps/reorder`,
      {
        method: "POST",
        body: JSON.stringify({ order }),
      },
    );
    await refreshAgentsPanel();
  };

  return {
    closeAgentStepForm,
    handleDeleteAgentStep,
    handleMoveAgentStep,
    handleOpenAgentStepForm,
    handleSaveAgentStep,
  };
}
