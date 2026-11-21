import { useMemo, type FormEvent } from "react";
import type { PanelAgent } from "../types/adminPanelTypes.agents";
import { createAgentStepFormActions } from "./useAdminAgentForms.steps";
import type { UseAdminAgentFormsArgs } from "./useAdminAgentForms.types";
import {
  agentFormSettersFrom,
  createRefreshAgentsPanel,
  openAgentForm,
  saveAgent,
} from "./useAdminAgentForms.save";

export function useAdminAgentForms(args: UseAdminAgentFormsArgs) {
  const availableAgentModes = args.agentModes;
  const agentModeNameByKey = useMemo(
    () => new Map(availableAgentModes.map((mode) => [mode.key, mode.name])),
    [availableAgentModes],
  );
  const agentFormSetters = agentFormSettersFrom(args);

  const refreshAgentsPanel = createRefreshAgentsPanel(args);

  const {
    closeAgentStepForm,
    handleDeleteAgentStep,
    handleMoveAgentStep,
    handleOpenAgentStepForm,
    handleSaveAgentStep,
  } = createAgentStepFormActions(args, refreshAgentsPanel);

  const handleOpenAgentForm = (agent?: PanelAgent | null) =>
    openAgentForm(args, agentFormSetters, availableAgentModes, agent);

  const closeAgentForm = () => {
    args.setShowAgentForm(false);
    args.setEditingAgent(null);
    args.setAgentFormError(null);
  };
  const handleSaveAgent = (event: FormEvent) =>
    saveAgent(args, refreshAgentsPanel, closeAgentForm, event);

  const handleDeleteAgent = async (agent: PanelAgent) => {
    if (!window.confirm(`Delete agent "${agent.name}"?`)) return;
    await args.readJson(`/admin/chat/api/panel/agents/${agent.id}`, {
      method: "DELETE",
    });
    await refreshAgentsPanel();
  };

  return {
    agentModeNameByKey,
    availableAgentModes,
    closeAgentForm,
    closeAgentStepForm,
    handleDeleteAgent,
    handleDeleteAgentStep,
    handleMoveAgentStep,
    handleOpenAgentForm,
    handleOpenAgentStepForm,
    handleSaveAgent,
    handleSaveAgentStep,
    refreshAgentsPanel,
  };
}
