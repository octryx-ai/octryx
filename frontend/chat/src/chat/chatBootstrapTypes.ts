import type { Dispatch, SetStateAction } from "react";

import type { ChatState } from "../types";

export type LoadOptions = {
  preserveTrace?: boolean;
  silent?: boolean;
  // Reads only that session's view, so the reply is drawn without the whole bootstrap.
  sessionOnly?: boolean;
};

export type ChatBootstrapStateArgs = {
  chatState: ChatState | null;
  setChatState: Dispatch<SetStateAction<ChatState | null>>;
  setSelectedProjectId: Dispatch<SetStateAction<string>>;
  setSelectedRuntimeTargetId: Dispatch<SetStateAction<string>>;
  setSelectedThinkingLevel: Dispatch<SetStateAction<string>>;
  setSelectedAgentGroupId: Dispatch<SetStateAction<string>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSelectedModeKey: Dispatch<SetStateAction<string>>;
  setRoutingOverridesEnabled: Dispatch<SetStateAction<boolean>>;
  setRenameValue: Dispatch<SetStateAction<string>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setLoading: Dispatch<SetStateAction<boolean>>;
  setSending: Dispatch<SetStateAction<boolean>>;
  setPendingPrompt: Dispatch<SetStateAction<string | null>>;
  setRenameOpen: Dispatch<SetStateAction<boolean>>;
  setSidebarOpen: Dispatch<SetStateAction<boolean>>;
  setStatsOpen: Dispatch<SetStateAction<boolean>>;
  setTaskErrorOpen: Dispatch<SetStateAction<boolean>>;
  setTraceOpen: Dispatch<SetStateAction<boolean>>;
  setTtsEnabled: Dispatch<SetStateAction<boolean>>;
};
