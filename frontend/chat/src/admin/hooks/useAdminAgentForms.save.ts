// Agent form persistence: the setter bundle the form helpers fill, the panel refresh, the agent save
// (tool and reply-format checks first, then PUT or POST).
import type { FormEvent } from "react";
import type { AgentBuilderMeta, PanelAgent } from "../types/adminPanelTypes.agents";
import { buildAgentPayload, hydrateAgentFormState, resetAgentFormState } from "./useAdminAgentForms.helpers";
import { resolveSafeDefaultMode } from "./useAdminAgentForms.defaults";
import type { UseAdminAgentFormsArgs } from "./useAdminAgentForms.types";
import { toolSurfaceForSave, type ToolSurface } from "../components/agentsTab/agentToolSurface";
import { replyFormatForSave, replyFormatSaveError } from "../components/agentsTab/agentReplyFormat";
import { type ReplyContract } from "../components/agentsTab/agentReplyFields";

export function agentFormSettersFrom(args: UseAdminAgentFormsArgs) {
  return {
  setEditingAgent: args.setEditingAgent,
  setAgentFormName: args.setAgentFormName,
  setAgentFormDescription: args.setAgentFormDescription,
  setAgentFormGoal: args.setAgentFormGoal,
  setAgentFormType: args.setAgentFormType,
  setAgentFormThinking: args.setAgentFormThinking,
  setAgentFormRuntimeId: args.setAgentFormRuntimeId,
  setAgentFormGroupId: args.setAgentFormGroupId,
  setAgentFormBranchPrefix: args.setAgentFormBranchPrefix,
  setAgentFormRequireSelfReview: args.setAgentFormRequireSelfReview,
  setAgentFormToolSurface: args.setAgentFormToolSurface,
  setAgentFormReplyFormat: args.setAgentFormReplyFormat,
  setAgentFormSystemPrompt: args.setAgentFormSystemPrompt,
  setAgentFormOutputPrompt: args.setAgentFormOutputPrompt,
  setAgentFormSetup: args.setAgentFormSetup,
  setAgentFormPreferredSkillIds: args.setAgentFormPreferredSkillIds,
  setAgentFormBlockedSkillIds: args.setAgentFormBlockedSkillIds,
  setAgentFormActive: args.setAgentFormActive,
  setAgentFormError: args.setAgentFormError,
  };
}

export function openAgentForm(
  args: UseAdminAgentFormsArgs,
  agentFormSetters: ReturnType<typeof agentFormSettersFrom>,
  availableAgentModes: UseAdminAgentFormsArgs["agentModes"],
  agent?: PanelAgent | null,
) {
  if (!agent) {
    // Least-privileged mode from the live catalog; "" forces an explicit choice.
    resetAgentFormState(
      agentFormSetters,
      resolveSafeDefaultMode(
        args.agentBuilderMeta?.agent_modes?.length
          ? args.agentBuilderMeta.agent_modes
          : availableAgentModes,
      ),
    );
    args.setShowAgentForm(true);
    return;
  }
  hydrateAgentFormState(agentFormSetters, agent);
  agentFormSetters.setEditingAgent(agent);
  args.setShowAgentForm(true);
}

export function createRefreshAgentsPanel(args: UseAdminAgentFormsArgs) {
  return async () => {
  const [agentData, meta] = await Promise.all([
    args.readJson<PanelAgent[]>("/admin/chat/api/panel/agents"),
    args.readJson<AgentBuilderMeta>("/admin/chat/api/panel/agents/meta"),
  ]);
  args.setPanelAgents(agentData);
  args.setAgentBuilderMeta(meta);
  if (
    args.selectedAgentPanelId &&
    !agentData.some((agent) => agent.id === args.selectedAgentPanelId)
  ) {
    args.setSelectedAgentPanelId(null);
  }
  };
}

type SaveChoices =
  | { error: string }
  | { error: null; toolSurface: ToolSurface; replyContract: ReplyContract | undefined };

function agentSaveChoices(args: UseAdminAgentFormsArgs): SaveChoices {
  const toolSurface = toolSurfaceForSave(args.agentFormToolSurface);
  if (!toolSurface.ok) return { error: toolSurface.error };
  const replyFormat = replyFormatForSave(args.agentFormReplyFormat);
  if (!replyFormat.ok) return { error: replyFormat.error };
  return { error: null, toolSurface: toolSurface.value, replyContract: replyFormat.send ? replyFormat.value : undefined };
}

function agentPayloadFromForm(
  args: UseAdminAgentFormsArgs,
  toolSurface: ToolSurface,
  replyContract: ReplyContract | undefined,
) {
  return buildAgentPayload({
    name: args.agentFormName,
    description: args.agentFormDescription,
    goal: args.agentFormGoal,
    type: args.agentFormType,
    thinking: args.agentFormThinking,
    runtimeId: args.agentFormRuntimeId,
    groupId: args.agentFormGroupId,
    branchPrefix: args.agentFormBranchPrefix,
    requireSelfReview: args.agentFormRequireSelfReview,
    toolSurface,
    replyContract,
    systemPrompt: args.agentFormSystemPrompt,
    outputPrompt: args.agentFormOutputPrompt,
    setup: args.agentFormSetup,
    preferredSkillIds: args.agentFormPreferredSkillIds,
    blockedSkillIds: args.agentFormBlockedSkillIds,
    isActive: args.agentFormActive,
  });
}

export async function saveAgent(
  args: UseAdminAgentFormsArgs,
  refreshAgentsPanel: () => Promise<void>,
  closeAgentForm: () => void,
  event: FormEvent,
) {
  event.preventDefault();
  const choices = agentSaveChoices(args);
  if (choices.error !== null) {
    args.setAgentFormError(choices.error);
    return;
  }
  args.setAgentFormLoading(true);
  args.setAgentFormError(null);
  try {
    const payload = agentPayloadFromForm(args, choices.toolSurface, choices.replyContract);
    const saved = args.editingAgent
      ? await args.readJson<PanelAgent>(
          `/admin/chat/api/panel/agents/${args.editingAgent.id}`,
          {
            method: "PUT",
            body: JSON.stringify(payload),
          },
        )
      : await args.readJson<PanelAgent>("/admin/chat/api/panel/agents", {
          method: "POST",
          body: JSON.stringify(payload),
        });
    await refreshAgentsPanel();
    args.setSelectedAgentPanelId(saved.id);
    closeAgentForm();
  } catch (error) {
    // An invalid saved output format makes the server refuse every save; say why.
    args.setAgentFormError(
      replyFormatSaveError(
        args.agentFormReplyFormat,
        error instanceof Error ? error.message : "Save failed",
      ),
    );
  } finally {
    args.setAgentFormLoading(false);
  }
}
