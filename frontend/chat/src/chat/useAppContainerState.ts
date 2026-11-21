import { useRef, useState } from "react";

import type { ChatState } from "../types";
import type { ToolArtifact } from "../chatThreadTypes";
import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { DraftAttachment } from "./useComposerInteractions.types";
import type { WorkspaceArea } from "./workspaceAreas";
import { readAreaTabFromSearch, workspaceAreaFromKey } from "./areaNavigation";

type ChatTheme = "dark" | "light";
const CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY =
  "octryx.chat.sidebarCollapsed";

function readChatSidebarCollapsedPreference(): boolean {
  try {
    return (
      window.localStorage.getItem(CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY) === "true"
    );
  } catch {
    return false;
  }
}

function storeChatSidebarCollapsedPreference(collapsed: boolean) {
  try {
    window.localStorage.setItem(
      CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY,
      String(collapsed),
    );
  } catch {
    // Collapsing still works for the current render when storage is unavailable.
  }
}

// The area of the address; an unknown area key opens the chat.
function readInitialWorkspaceArea(): WorkspaceArea {
  try {
    return workspaceAreaFromKey(new URL(window.location.href).searchParams.get("area")) ?? "chat";
  } catch {
    return "chat";
  }
}
// The chat, its theme and the routing choices of the composer, and the open/closed state of header panels.
function useChatRoutingState(chatThemeStorageKey: string) {
  const [chatState, setChatState] = useState<ChatState | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [editingMessage, setEditingMessage] = useState<{
    id: string;
    content: string;
  } | null>(null);
  const [chatTheme, setChatTheme] = useState<ChatTheme>(() => {
    const stored = window.localStorage.getItem(chatThemeStorageKey);
    return stored === "light" ? "light" : "dark";
  });
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedRuntimeTargetId, setSelectedRuntimeTargetId] = useState("");
  const [selectedThinkingLevel, setSelectedThinkingLevel] = useState("light");
  const [selectedAgentGroupId, setSelectedAgentGroupId] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [routingOverridesEnabled, setRoutingOverridesEnabled] = useState(false);
  const [selectedModeKey, setSelectedModeKey] = useState("diagnosis");
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [taskErrorOpen, setTaskErrorOpen] = useState(false);
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  return {
    chatState, setChatState, composerValue, setComposerValue, editingMessage, setEditingMessage, chatTheme,
    setChatTheme, selectedProjectId, setSelectedProjectId, selectedRuntimeTargetId, setSelectedRuntimeTargetId,
    selectedThinkingLevel, setSelectedThinkingLevel, selectedAgentGroupId,
    setSelectedAgentGroupId, selectedAgentId, setSelectedAgentId, routingOverridesEnabled,
    setRoutingOverridesEnabled, selectedModeKey, setSelectedModeKey, profileDropdownOpen, setProfileDropdownOpen,
    ttsEnabled, setTtsEnabled, traceOpen, setTraceOpen, statsOpen, setStatsOpen, taskErrorOpen, setTaskErrorOpen,
    workspacePanelOpen, setWorkspacePanelOpen,
  };
}

// The shell: sidebar, area, admin start tab, rename dialog, thread search and the load/send state.
function useChatShellState() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chatSidebarCollapsed, setChatSidebarCollapsedState] = useState(
    readChatSidebarCollapsedPreference,
  );
  const [activeArea, setActiveArea] =
    useState<WorkspaceArea>(readInitialWorkspaceArea);
  // The area resolver validates this against the active area.
  const [adminPanelInitialTab, setAdminPanelInitialTab] = useState<AdminTab>(
    () => (readAreaTabFromSearch(window.location.search) || "adminProblems") as AdminTab,
  );
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [threadSearchQuery, setThreadSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const setChatSidebarCollapsed = (
    value: boolean | ((current: boolean) => boolean),
  ) => {
    setChatSidebarCollapsedState((current) => {
      const next = typeof value === "function" ? value(current) : value;
      storeChatSidebarCollapsedPreference(next);
      return next;
    });
  };

  return {
    sidebarOpen, setSidebarOpen, chatSidebarCollapsed, setChatSidebarCollapsed, activeArea, setActiveArea,
    adminPanelInitialTab, setAdminPanelInitialTab, renameOpen, setRenameOpen, renameValue, setRenameValue,
    threadSearchQuery, setThreadSearchQuery, loading, setLoading, sending, setSending, error, setError,
    pendingPrompt, setPendingPrompt,
  };
}

// The composer: mentions, slash commands, attachments, preview and the message history.
function useComposerState(chatHistoryStorageKey: string) {
  const [atMention, setAtMention] = useState<{
    open: boolean;
    query: string;
    startPos: number;
  }>({
    open: false,
    query: "",
    startPos: -1,
  });
  const [slashCommand, setSlashCommand] = useState<{
    open: boolean;
    query: string;
  }>({ open: false, query: "" });
  const [generateTaskResult, setGenerateTaskResult] = useState<{
    taskName: string;
    taskUrl: string;
  } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [draftAttachments, setDraftAttachments] = useState<DraftAttachment[]>(
    [],
  );
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const [previewArtifact, setPreviewArtifact] = useState<ToolArtifact | null>(
    null,
  );
  const [composerHistory, setComposerHistory] = useState<string[]>(() => {
    try {
      return JSON.parse(
        window.localStorage.getItem(chatHistoryStorageKey) || "[]",
      ) as string[];
    } catch {
      return [];
    }
  });
  const [composerHistoryIndex, setComposerHistoryIndex] = useState(-1);
  const composerNavigationDraftRef = useRef("");
  return {
    atMention, setAtMention, slashCommand, setSlashCommand, generateTaskResult, setGenerateTaskResult, textareaRef,
    fileInputRef, draftAttachments, setDraftAttachments, uploadingAttachments, setUploadingAttachments,
    composerDragActive, setComposerDragActive, previewArtifact, setPreviewArtifact, composerHistory,
    setComposerHistory, composerHistoryIndex, setComposerHistoryIndex, composerNavigationDraftRef,
  };
}

export function useAppContainerState({
  chatThemeStorageKey,
  chatHistoryStorageKey,
}: {
  chatThemeStorageKey: string;
  chatHistoryStorageKey: string;
}) {
  return {
    ...useChatRoutingState(chatThemeStorageKey),
    ...useChatShellState(),
    ...useComposerState(chatHistoryStorageKey),
  };
}
