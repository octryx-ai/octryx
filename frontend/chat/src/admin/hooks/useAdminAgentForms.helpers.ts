import type { PanelAgent, PanelAgentStep } from "../types/adminPanelTypes.agents";
import type {
  AgentFormSetters,
  AgentFormValues,
  AgentStepFormSetters,
  AgentStepFormValues,
} from "./useAdminAgentForms.types";
import { NEW_AGENT_DEFAULTS } from "./useAdminAgentForms.defaults";
import { TOOL_SURFACE_DEFAULT, toolSurfaceFromAgent } from "../components/agentsTab/agentToolSurface";
import { defaultReplyFormat } from "../components/agentsTab/agentReplyFields";
import { replyFormatFromAgent } from "../components/agentsTab/agentReplyContract";
import { DEFAULT_AGENT_SETUP, agentSetupFromAgent } from "../components/agentsTab/agentSetupFields";

export function resetAgentFormState(
  setters: AgentFormSetters,
  defaultAgentMode: string,
) {
  setters.setEditingAgent(null);
  setters.setAgentFormName("");
  setters.setAgentFormDescription("");
  setters.setAgentFormGoal("");
  setters.setAgentFormType(defaultAgentMode);
  setters.setAgentFormThinking(NEW_AGENT_DEFAULTS.thinking);
  setters.setAgentFormRuntimeId("");
  setters.setAgentFormGroupId("");
  setters.setAgentFormBranchPrefix(NEW_AGENT_DEFAULTS.branchPrefix);
  setters.setAgentFormRequireSelfReview(false);
  setters.setAgentFormToolSurface(TOOL_SURFACE_DEFAULT);
  setters.setAgentFormReplyFormat(defaultReplyFormat());
  setters.setAgentFormSystemPrompt("");
  setters.setAgentFormOutputPrompt("");
  setters.setAgentFormSetup(DEFAULT_AGENT_SETUP);
  setters.setAgentFormPreferredSkillIds([]);
  setters.setAgentFormBlockedSkillIds([]);
  setters.setAgentFormActive(NEW_AGENT_DEFAULTS.isActive);
  setters.setAgentFormError(null);
}

export function hydrateAgentFormState(
  setters: AgentFormSetters,
  agent: PanelAgent,
) {
  setters.setEditingAgent(agent);
  setters.setAgentFormName(agent.name || "");
  setters.setAgentFormDescription(agent.description || "");
  setters.setAgentFormGoal(agent.goal || "");
  setters.setAgentFormType(agent.agentType || agent.agent_type || "diagnosis");
  setters.setAgentFormThinking(agent.thinkingLevel || "light");
  setters.setAgentFormRuntimeId(agent.runtimeTargetId || "");
  setters.setAgentFormGroupId(agent.groupId || "");
  setters.setAgentFormBranchPrefix(agent.branchPrefix || "octryx");
  setters.setAgentFormRequireSelfReview(Boolean(agent.requireSelfReview));
  setters.setAgentFormToolSurface(toolSurfaceFromAgent(agent));
  setters.setAgentFormReplyFormat(replyFormatFromAgent(agent));
  setters.setAgentFormSystemPrompt(agent.systemPrompt || "");
  setters.setAgentFormOutputPrompt(agent.outputPrompt || "");
  setters.setAgentFormSetup(agentSetupFromAgent(agent));
  setters.setAgentFormPreferredSkillIds(
    normalizeSkillIds(agent.skillPreferences?.preferred_skill_ids),
  );
  setters.setAgentFormBlockedSkillIds(
    normalizeSkillIds(agent.skillPreferences?.blocked_skill_ids),
  );
  setters.setAgentFormActive(agent.isActive ?? agent.is_active ?? true);
  setters.setAgentFormError(null);
}

export function buildAgentPayload(values: AgentFormValues) {
  return {
    name: values.name,
    description: values.description,
    goal: values.goal,
    thinking_level: values.thinking,
    runtime_target_id: values.runtimeId,
    group_id: values.groupId,
    branch_prefix: values.branchPrefix,
    require_self_review: values.requireSelfReview,
    // The write body is snake_case (backend AgentCreateRequest); the read payload names it toolSurface.
    tool_surface: values.toolSurface,
    // The shared request key; present only when the author set or changed the format.
    ...(values.replyContract ? { reply_contract: values.replyContract } : {}),
    system_prompt: values.systemPrompt,
    output_prompt: values.outputPrompt,
    capability_ceiling: values.setup.capabilityCeiling,
    default_workflow_key: values.setup.defaultWorkflowKey,
    execution_mode: values.setup.executionMode,
    skill_preferences: {
      preferred_skill_ids: values.preferredSkillIds,
      blocked_skill_ids: values.blockedSkillIds,
    },
    is_active: values.isActive,
  };
}

function normalizeSkillIds(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item).trim()).filter(Boolean)
    : [];
}

export function resetAgentStepFormState(
  setters: AgentStepFormSetters,
  defaultStepType: string,
) {
  setters.setEditingAgentStep(null);
  setters.setAgentStepFormName("");
  setters.setAgentStepFormType(defaultStepType);
  setters.setAgentStepFormInstructions("");
  setters.setAgentStepFormSuccessCriteria("");
  setters.setAgentStepFormAllowedTools("");
  setters.setAgentStepFormConfig("{\n  \n}");
  setters.setAgentStepFormEnabled(true);
  setters.setAgentStepFormError(null);
}

export function hydrateAgentStepFormState(
  setters: AgentStepFormSetters,
  step: PanelAgentStep,
) {
  setters.setEditingAgentStep(step);
  setters.setAgentStepFormName(step.name || "");
  setters.setAgentStepFormType(step.stepType || "analysis");
  setters.setAgentStepFormInstructions(step.instructions || "");
  setters.setAgentStepFormSuccessCriteria(step.successCriteria || "");
  setters.setAgentStepFormAllowedTools((step.allowedTools || []).join(", "));
  setters.setAgentStepFormConfig(
    JSON.stringify(step.stepConfig || {}, null, 2),
  );
  setters.setAgentStepFormEnabled(step.isEnabled ?? true);
  setters.setAgentStepFormError(null);
}

export function buildAgentStepPayload(values: AgentStepFormValues) {
  let parsedStepConfig: Record<string, unknown> = {};
  try {
    parsedStepConfig = JSON.parse(values.config || "{}");
  } catch {
    throw new Error("Step config must be valid JSON");
  }
  return {
    name: values.name,
    step_type: values.type,
    instructions: values.instructions,
    success_criteria: values.successCriteria,
    allowed_tools: values.allowedTools
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    step_config: parsedStepConfig,
    is_enabled: values.enabled,
  };
}

export function buildReorderedStepIds(
  panelAgents: PanelAgent[],
  agentId: string,
  stepId: string,
  direction: "up" | "down",
): string[] | null {
  const agent = panelAgents.find((item) => item.id === agentId);
  const steps = [...(agent?.steps || [])].sort(
    (left, right) => left.position - right.position,
  );
  const index = steps.findIndex((step) => step.id === stepId);
  if (index < 0) return null;
  const swapIndex = direction === "up" ? index - 1 : index + 1;
  if (swapIndex < 0 || swapIndex >= steps.length) return null;
  [steps[index], steps[swapIndex]] = [steps[swapIndex], steps[index]];
  return steps.map((step) => step.id);
}
