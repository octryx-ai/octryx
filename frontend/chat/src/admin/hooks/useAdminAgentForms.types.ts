import type { Dispatch, SetStateAction } from "react";
import type { AdminAgentMode, AgentBuilderMeta, PanelAgent, PanelAgentStep } from "../types/adminPanelTypes.agents";
import type { ToolSurface } from "../components/agentsTab/agentToolSurface";
import type { AgentSetupFields } from "../components/agentsTab/agentSetupFields";
import type { ReplyContract, ReplyFormatState } from "../components/agentsTab/agentReplyFields";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type UseAdminAgentFormsArgs = {
  readJson: ReadJsonFn;
  agentModes: AdminAgentMode[];
  panelAgents: PanelAgent[];
  setPanelAgents: Dispatch<SetStateAction<PanelAgent[]>>;
  selectedAgentPanelId: string | null;
  setSelectedAgentPanelId: Dispatch<SetStateAction<string | null>>;
  agentBuilderMeta: AgentBuilderMeta | null;
  setAgentBuilderMeta: Dispatch<SetStateAction<AgentBuilderMeta | null>>;
  setShowAgentForm: Dispatch<SetStateAction<boolean>>;
  editingAgent: PanelAgent | null;
  setEditingAgent: Dispatch<SetStateAction<PanelAgent | null>>;
  agentFormName: string;
  setAgentFormName: Dispatch<SetStateAction<string>>;
  agentFormDescription: string;
  setAgentFormDescription: Dispatch<SetStateAction<string>>;
  agentFormGoal: string;
  setAgentFormGoal: Dispatch<SetStateAction<string>>;
  agentFormType: string;
  setAgentFormType: Dispatch<SetStateAction<string>>;
  agentFormThinking: string;
  setAgentFormThinking: Dispatch<SetStateAction<string>>;
  agentFormRuntimeId: string;
  setAgentFormRuntimeId: Dispatch<SetStateAction<string>>;
  agentFormGroupId: string;
  setAgentFormGroupId: Dispatch<SetStateAction<string>>;
  agentFormBranchPrefix: string;
  setAgentFormBranchPrefix: Dispatch<SetStateAction<string>>;
  agentFormRequireSelfReview: boolean;
  setAgentFormRequireSelfReview: Dispatch<SetStateAction<boolean>>;
  agentFormToolSurface: string;
  setAgentFormToolSurface: Dispatch<SetStateAction<string>>;
  agentFormReplyFormat: ReplyFormatState;
  setAgentFormReplyFormat: Dispatch<SetStateAction<ReplyFormatState>>;
  agentFormSystemPrompt: string;
  setAgentFormSystemPrompt: Dispatch<SetStateAction<string>>;
  agentFormOutputPrompt: string;
  setAgentFormOutputPrompt: Dispatch<SetStateAction<string>>;
  agentFormSetup: AgentSetupFields;
  setAgentFormSetup: Dispatch<SetStateAction<AgentSetupFields>>;
  agentFormPreferredSkillIds: string[];
  setAgentFormPreferredSkillIds: Dispatch<SetStateAction<string[]>>;
  agentFormBlockedSkillIds: string[];
  setAgentFormBlockedSkillIds: Dispatch<SetStateAction<string[]>>;
  agentFormActive: boolean;
  setAgentFormActive: Dispatch<SetStateAction<boolean>>;
  setAgentFormLoading: Dispatch<SetStateAction<boolean>>;
  setAgentFormError: Dispatch<SetStateAction<string | null>>;
  agentStepFormFor: string | null;
  setAgentStepFormFor: Dispatch<SetStateAction<string | null>>;
  editingAgentStep: PanelAgentStep | null;
  setEditingAgentStep: Dispatch<SetStateAction<PanelAgentStep | null>>;
  agentStepFormName: string;
  setAgentStepFormName: Dispatch<SetStateAction<string>>;
  agentStepFormType: string;
  setAgentStepFormType: Dispatch<SetStateAction<string>>;
  agentStepFormInstructions: string;
  setAgentStepFormInstructions: Dispatch<SetStateAction<string>>;
  agentStepFormSuccessCriteria: string;
  setAgentStepFormSuccessCriteria: Dispatch<SetStateAction<string>>;
  agentStepFormAllowedTools: string;
  setAgentStepFormAllowedTools: Dispatch<SetStateAction<string>>;
  agentStepFormConfig: string;
  setAgentStepFormConfig: Dispatch<SetStateAction<string>>;
  agentStepFormEnabled: boolean;
  setAgentStepFormEnabled: Dispatch<SetStateAction<boolean>>;
  setAgentStepFormLoading: Dispatch<SetStateAction<boolean>>;
  setAgentStepFormError: Dispatch<SetStateAction<string | null>>;
};

export type AgentFormSetters = {
  setEditingAgent: Dispatch<SetStateAction<PanelAgent | null>>;
  setAgentFormName: Dispatch<SetStateAction<string>>;
  setAgentFormDescription: Dispatch<SetStateAction<string>>;
  setAgentFormGoal: Dispatch<SetStateAction<string>>;
  setAgentFormType: Dispatch<SetStateAction<string>>;
  setAgentFormThinking: Dispatch<SetStateAction<string>>;
  setAgentFormRuntimeId: Dispatch<SetStateAction<string>>;
  setAgentFormGroupId: Dispatch<SetStateAction<string>>;
  setAgentFormBranchPrefix: Dispatch<SetStateAction<string>>;
  setAgentFormRequireSelfReview: Dispatch<SetStateAction<boolean>>;
  setAgentFormToolSurface: Dispatch<SetStateAction<string>>;
  setAgentFormReplyFormat: Dispatch<SetStateAction<ReplyFormatState>>;
  setAgentFormSystemPrompt: Dispatch<SetStateAction<string>>;
  setAgentFormOutputPrompt: Dispatch<SetStateAction<string>>;
  setAgentFormSetup: Dispatch<SetStateAction<AgentSetupFields>>;
  setAgentFormPreferredSkillIds: Dispatch<SetStateAction<string[]>>;
  setAgentFormBlockedSkillIds: Dispatch<SetStateAction<string[]>>;
  setAgentFormActive: Dispatch<SetStateAction<boolean>>;
  setAgentFormError: Dispatch<SetStateAction<string | null>>;
};

export type AgentFormValues = {
  name: string;
  description: string;
  goal: string;
  type: string;
  thinking: string;
  runtimeId: string;
  groupId: string;
  branchPrefix: string;
  requireSelfReview: boolean;
  // Only a known value is sent; the save handler refuses an unknown one first.
  toolSurface: ToolSurface;
  // Sent only when set: an unchanged or unrecognised output format is omitted and kept by the server.
  replyContract?: ReplyContract;
  systemPrompt: string;
  outputPrompt: string;
  setup: AgentSetupFields;
  preferredSkillIds: string[];
  blockedSkillIds: string[];
  isActive: boolean;
};

export type AgentStepFormSetters = {
  setEditingAgentStep: Dispatch<SetStateAction<PanelAgentStep | null>>;
  setAgentStepFormName: Dispatch<SetStateAction<string>>;
  setAgentStepFormType: Dispatch<SetStateAction<string>>;
  setAgentStepFormInstructions: Dispatch<SetStateAction<string>>;
  setAgentStepFormSuccessCriteria: Dispatch<SetStateAction<string>>;
  setAgentStepFormAllowedTools: Dispatch<SetStateAction<string>>;
  setAgentStepFormConfig: Dispatch<SetStateAction<string>>;
  setAgentStepFormEnabled: Dispatch<SetStateAction<boolean>>;
  setAgentStepFormError: Dispatch<SetStateAction<string | null>>;
};

export type AgentStepFormValues = {
  name: string;
  type: string;
  instructions: string;
  successCriteria: string;
  allowedTools: string;
  config: string;
  enabled: boolean;
};
