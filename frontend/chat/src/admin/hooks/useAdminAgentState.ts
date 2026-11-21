import { useState } from "react";
import { DEFAULT_AGENT_SETUP, type AgentSetupFields } from "../components/agentsTab/agentSetupFields";
import type { AgentBuilderMeta, PanelAgent, PanelAgentStep } from "../types/adminPanelTypes.agents";
import { NEW_AGENT_DEFAULTS } from "./useAdminAgentForms.defaults";
import { TOOL_SURFACE_DEFAULT } from "../components/agentsTab/agentToolSurface";
import { defaultReplyFormat, type ReplyFormatState } from "../components/agentsTab/agentReplyFields";

// The agent list, the selected agent and the open agent form.
function useAgentListState() {
  const [panelAgents, setPanelAgents] = useState<PanelAgent[]>([]);
  const [agentBuilderMeta, setAgentBuilderMeta] =
    useState<AgentBuilderMeta | null>(null);
  const [showAgentForm, setShowAgentForm] = useState(false);
  const [editingAgent, setEditingAgent] = useState<PanelAgent | null>(null);
  const [selectedAgentPanelId, setSelectedAgentPanelId] = useState<
    string | null
  >(null);
  return {
    panelAgents,
    setPanelAgents,
    agentBuilderMeta,
    setAgentBuilderMeta,
    showAgentForm,
    setShowAgentForm,
    editingAgent,
    setEditingAgent,
    selectedAgentPanelId,
    setSelectedAgentPanelId,
  };
}

// The identity and runtime fields of the agent form.
function useAgentFormBasics() {
  const [agentFormName, setAgentFormName] = useState("");
  const [agentFormDescription, setAgentFormDescription] = useState("");
  const [agentFormGoal, setAgentFormGoal] = useState("");
  const [agentFormType, setAgentFormType] = useState("diagnosis");
  const [agentFormThinking, setAgentFormThinking] = useState("light");
  const [agentFormRuntimeId, setAgentFormRuntimeId] = useState("");
  const [agentFormGroupId, setAgentFormGroupId] = useState("");
  const [agentFormBranchPrefix, setAgentFormBranchPrefix] =
    useState("octryx");
  const [agentFormRequireSelfReview, setAgentFormRequireSelfReview] =
    useState(false);
  return {
    agentFormName,
    setAgentFormName,
    agentFormDescription,
    setAgentFormDescription,
    agentFormGoal,
    setAgentFormGoal,
    agentFormType,
    setAgentFormType,
    agentFormThinking,
    setAgentFormThinking,
    agentFormRuntimeId,
    setAgentFormRuntimeId,
    agentFormGroupId,
    setAgentFormGroupId,
    agentFormBranchPrefix,
    setAgentFormBranchPrefix,
    agentFormRequireSelfReview,
    setAgentFormRequireSelfReview,
  };
}

// The tool surface, reply format, prompts, setup, skills and activation fields of the agent form.
function useAgentFormContent() {
  // The saved `toolSurface`; an unknown server value is kept verbatim (see agentToolSurface).
  const [agentFormToolSurface, setAgentFormToolSurface] =
    useState<string>(TOOL_SURFACE_DEFAULT);
  // The saved `replyContract` as form state; an unrecognised server value is kept (see agentReplyFormat).
  const [agentFormReplyFormat, setAgentFormReplyFormat] =
    useState<ReplyFormatState>(defaultReplyFormat);
  const [agentFormSystemPrompt, setAgentFormSystemPrompt] = useState("");
  const [agentFormOutputPrompt, setAgentFormOutputPrompt] = useState("");
  const [agentFormSetup, setAgentFormSetup] = useState<AgentSetupFields>(DEFAULT_AGENT_SETUP);
  const [agentFormPreferredSkillIds, setAgentFormPreferredSkillIds] = useState<
    string[]
  >([]);
  const [agentFormBlockedSkillIds, setAgentFormBlockedSkillIds] = useState<
    string[]
  >([]);
  const [agentFormActive, setAgentFormActive] = useState<boolean>(
    NEW_AGENT_DEFAULTS.isActive,
  );
  const [agentFormLoading, setAgentFormLoading] = useState(false);
  const [agentFormError, setAgentFormError] = useState<string | null>(null);
  return {
    agentFormToolSurface,
    setAgentFormToolSurface,
    agentFormReplyFormat,
    setAgentFormReplyFormat,
    agentFormSystemPrompt,
    setAgentFormSystemPrompt,
    agentFormOutputPrompt,
    setAgentFormOutputPrompt,
    agentFormSetup,
    setAgentFormSetup,
    agentFormPreferredSkillIds,
    setAgentFormPreferredSkillIds,
    agentFormBlockedSkillIds,
    setAgentFormBlockedSkillIds,
    agentFormActive,
    setAgentFormActive,
    agentFormLoading,
    setAgentFormLoading,
    agentFormError,
    setAgentFormError,
  };
}

// The agent step form.
function useAgentStepFormState() {
  const [agentStepFormFor, setAgentStepFormFor] = useState<string | null>(null);
  const [editingAgentStep, setEditingAgentStep] =
    useState<PanelAgentStep | null>(null);
  const [agentStepFormName, setAgentStepFormName] = useState("");
  const [agentStepFormType, setAgentStepFormType] = useState("analysis");
  const [agentStepFormInstructions, setAgentStepFormInstructions] =
    useState("");
  const [agentStepFormSuccessCriteria, setAgentStepFormSuccessCriteria] =
    useState("");
  const [agentStepFormAllowedTools, setAgentStepFormAllowedTools] =
    useState("");
  const [agentStepFormConfig, setAgentStepFormConfig] = useState("{\n  \n}");
  const [agentStepFormEnabled, setAgentStepFormEnabled] = useState(true);
  const [agentStepFormLoading, setAgentStepFormLoading] = useState(false);
  const [agentStepFormError, setAgentStepFormError] = useState<string | null>(
    null,
  );
  return {
    agentStepFormFor,
    setAgentStepFormFor,
    editingAgentStep,
    setEditingAgentStep,
    agentStepFormName,
    setAgentStepFormName,
    agentStepFormType,
    setAgentStepFormType,
    agentStepFormInstructions,
    setAgentStepFormInstructions,
    agentStepFormSuccessCriteria,
    setAgentStepFormSuccessCriteria,
    agentStepFormAllowedTools,
    setAgentStepFormAllowedTools,
    agentStepFormConfig,
    setAgentStepFormConfig,
    agentStepFormEnabled,
    setAgentStepFormEnabled,
    agentStepFormLoading,
    setAgentStepFormLoading,
    agentStepFormError,
    setAgentStepFormError,
  };
}

export function useAdminAgentState() {
  const listState = useAgentListState();
  const formBasics = useAgentFormBasics();
  const formContent = useAgentFormContent();
  const stepFormState = useAgentStepFormState();
  return { ...listState, ...formBasics, ...formContent, ...stepFormState };
}
