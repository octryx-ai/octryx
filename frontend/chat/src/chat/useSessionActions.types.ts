import type { Dispatch, SetStateAction } from "react";
import type { ChatState } from "../types";
import type { SelectedSession } from "../chatThreadTypes";
import type { DraftAttachment } from "./useComposerInteractions.types";

export type LoadOptions = {
  preserveTrace?: boolean;
  silent?: boolean;
};

export type UseSessionActionsArgs = {
  selectedSession: SelectedSession | null;
  selectedSessionIsRunning: boolean;
  selectedSessionIsArchived: boolean;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  selectedThinkingLevel: string;
  selectedAgentId: string;
  renameValue: string;
  sending: boolean;
  setSending: Dispatch<SetStateAction<boolean>>;
  setEditingMessage: Dispatch<
    SetStateAction<{ id: string; content: string } | null>
  >;
  setError: Dispatch<SetStateAction<string | null>>;
  setGenerateTaskResult: Dispatch<
    SetStateAction<{ taskName: string; taskUrl: string } | null>
  >;
  setPendingPrompt: Dispatch<SetStateAction<string | null>>;
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  applyState: (
    nextState: ChatState,
    search?: string,
    options?: LoadOptions,
  ) => void;
  loadState: (search?: string, options?: LoadOptions) => Promise<void>;
  handleSend: (overridePrompt?: string) => Promise<void>;
};
