import type {
  Dispatch,
  KeyboardEvent,
  MutableRefObject,
  SetStateAction,
} from "react";

export type AtMentionState = {
  open: boolean;
  query: string;
  startPos: number;
};

export type SlashCommandState = {
  open: boolean;
  query: string;
};

export type AgentOption = {
  id: string;
  name: string;
  groupId: string;
};

export type DraftAttachment = {
  id: string;
  name: string;
  path: string;
  relativePath: string;
  mediaType: string;
  sizeBytes: number;
  url: string;
};

export type SlashCommandOption = {
  name: string;
  description: string;
};

export type ComposerInteractionHandlers = {
  uploadDraftFiles: (files: FileList | File[]) => Promise<void>;
  removeDraftAttachment: (attachmentId: string) => void;
  handleComposerChange: (value: string) => void;
  handleSelectAtAgent: (agent: { id: string; name: string }) => void;
  handleAgentGroupChange: (nextGroupId: string) => void;
  handleAgentSelection: (nextAgentId: string) => void;
  handleComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  handleReuseMessage: (content: string) => void;
  handleEditMessage: (messageId: string, content: string) => void;
  handleCancelEditMessage: () => void;
};

export type UseComposerInteractionsArgs = {
  composerValue: string;
  setComposerValue: Dispatch<SetStateAction<string>>;
  atMention: AtMentionState;
  setAtMention: Dispatch<SetStateAction<AtMentionState>>;
  slashCommand: SlashCommandState;
  setSlashCommand: Dispatch<SetStateAction<SlashCommandState>>;
  composerHistory: string[];
  composerHistoryIndex: number;
  setComposerHistoryIndex: Dispatch<SetStateAction<number>>;
  composerNavigationDraftRef: MutableRefObject<string>;
  composerDraftKey: string;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
  handleSend: (overridePrompt?: string) => Promise<void>;
  setEditingMessage: Dispatch<
    SetStateAction<{ id: string; content: string } | null>
  >;
  agentOptions: AgentOption[];
  selectedAgentId: string;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSelectedModeKey: Dispatch<SetStateAction<string>>;
  setSelectedAgentGroupId: Dispatch<SetStateAction<string>>;
  setRoutingOverridesEnabled: Dispatch<SetStateAction<boolean>>;
  uploadingAttachments: boolean;
  setUploadingAttachments: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  selectedSessionId: string | null;
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
};
