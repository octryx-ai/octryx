import type { Dispatch, KeyboardEvent, RefObject, SetStateAction } from "react";

import type { AgentGroupOption, AgentModeOption, ChatAgentOption, RuntimeOption, WorkflowOption } from "../chatOptionTypes";
import type { SelectedSession } from "../chatThreadTypes";
import type { ComposerAgentIdentity } from "./chatAgentGuidance";

export type DraftAttachment = {
  id: string;
  name: string;
  path: string;
  relativePath: string;
  mediaType: string;
  sizeBytes: number;
  url: string;
};

export type ComposerShellProps = {
  selectedSession: SelectedSession | null;
  selectedSessionIsArchived?: boolean;
  selectedSessionIsRunning: boolean;
  editingMessage: { id: string; content: string } | null;
  onCancelEditMessage: () => void;
  generateTaskResult: { taskName: string; taskUrl: string } | null;
  setGenerateTaskResult: (
    value: { taskName: string; taskUrl: string } | null,
  ) => void;
  composerDragActive: boolean;
  setComposerDragActive: (value: boolean) => void;
  composerDisabled: boolean;
  fileInputRef: RefObject<HTMLInputElement>;
  uploadDraftFiles: (files: FileList | File[]) => Promise<void>;
  slashCommand: { open: boolean; query: string };
  slashCommands: { name: string; description: string }[];
  handleSend: (overridePrompt?: string) => Promise<void>;
  handleStop: () => Promise<void>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setSlashCommand: Dispatch<SetStateAction<{ open: boolean; query: string }>>;
  atMention: { open: boolean; query: string };
  routingOverridesEnabled: boolean;
  setRoutingOverridesEnabled: (value: boolean) => void;
  agentGroups: AgentGroupOption[];
  selectedAgentGroupId: string;
  setSelectedAgentGroupId: (value: string) => void;
  agentGroupPillLabel: string;
  selectedAgentId: string;
  selectedAgentSelectionSource?: string;
  setSelectedAgentId: (value: string) => void;
  agentPillLabel: string;
  // Derived by the host (chatAgentGuidance.ts); null shows no agent, undefined uses the local fallback.
  agentIdentity?: ComposerAgentIdentity | null;
  agentNotice?: { text: string; href: string } | null;
  chatAgentOptions: Array<{
    id: string;
    name: string;
    description: string;
    groupId: string;
    groupName?: string;
    isPrimary?: boolean;
  }>;
  handleSelectAtAgent: (agent: { id: string; name: string }) => void;
  draftAttachments: DraftAttachment[];
  uploadingAttachments: boolean;
  removeDraftAttachment: (attachmentId: string) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
  composerValue: string;
  handleComposerChange: (value: string) => void;
  handleComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  selectedRuntimeTargetId: string;
  setSelectedRuntimeTargetId: (value: string) => void;
  runtimeOptions: RuntimeOption[];
  runtimePillLabel: string;
  selectedProjectId: string;
  projectPillLabel: string;
  selectedThinkingLevel: string;
  setSelectedThinkingLevel: (value: string) => void;
  workflowOptions: WorkflowOption[];
  selectedWorkflowKey: string;
  setSelectedWorkflowKey: (value: string) => void;
  workflowPillLabel: string;
  selectedWorkflowCapability: "diagnosis" | "change" | "";
  sttAvailable: boolean;
  sttListening: boolean;
  startSTT: () => Promise<void>;
  showCanvas: boolean;
  openCanvas: () => Promise<void>;
  ttsEnabled: boolean;
  sending: boolean;
};

export type GroupedAgentPopup = {
  label: string;
  agents: Array<{
    id: string;
    name: string;
    description: string;
    groupId: string;
    groupName?: string;
  }>;
};

export type GroupedAgentSelect = {
  label: string;
  agents: Array<{
    id: string;
    name: string;
  }>;
};

export type ComposerAgentOption = Pick<
  ChatAgentOption,
  | "id"
  | "name"
  | "description"
  | "groupId"
  | "groupName"
  | "isPrimary"
>;
